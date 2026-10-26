#include "DecisionOutbox.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace pauseable {
namespace {

using Json = nlohmann::json;

std::string stableFileName(const std::string& eventId)
{
    std::uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char value : eventId) {
        hash ^= value;
        hash *= 1099511628211ULL;
    }

    std::string prefix;
    for (const unsigned char value : eventId) {
        if (prefix.size() >= 40) break;
        prefix.push_back(std::isalnum(value) != 0 || value == '-' || value == '_'
            ? static_cast<char>(value) : '_');
    }
    if (prefix.empty()) prefix = "event";

    std::ostringstream name;
    name << prefix << '-' << std::hex << std::setw(16) << std::setfill('0') << hash << ".json";
    return name.str();
}

void writeAtomically(const std::filesystem::path& path, const Json& document)
{
    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::trunc);
        if (!output.is_open()) throw std::runtime_error("Could not open Outbox temporary file");
        output << document.dump() << '\n';
        output.flush();
        if (!output.good()) throw std::runtime_error("Could not write Outbox item");
    }
    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(path, error);
        error.clear();
        std::filesystem::rename(temporary, path, error);
    }
    if (error) throw std::runtime_error("Could not replace Outbox item: " + error.message());
}

std::size_t jsonFileCount(const std::filesystem::path& directory)
{
    std::size_t count = 0;
    std::error_code error;
    if (!std::filesystem::exists(directory, error)) return 0;
    for (const auto& entry : std::filesystem::directory_iterator(directory)) {
        if (entry.is_regular_file() && entry.path().extension() == ".json") ++count;
    }
    return count;
}

}

struct DecisionOutbox::Impl {
    DecisionOutboxConfig config;
    Sender sender;
    StatusHandler statusHandler;
    std::filesystem::path pendingDirectory;
    std::filesystem::path deadDirectory;
    mutable std::mutex mutex;
    std::condition_variable condition;
    std::thread worker;
    std::atomic<bool> active{false};
    bool stopRequested{false};

    Impl(DecisionOutboxConfig value, Sender send, StatusHandler status)
        : config(std::move(value)), sender(std::move(send)), statusHandler(std::move(status))
    {
        if (config.directory.empty() || config.maximumPending == 0 ||
            config.maximumAttempts == 0 || config.initialRetryDelay.count() <= 0 ||
            config.maximumRetryDelay < config.initialRetryDelay || !sender || !statusHandler) {
            throw std::invalid_argument("Decision Outbox configuration is incomplete");
        }
        pendingDirectory = std::filesystem::path(config.directory) / "pending";
        deadDirectory = std::filesystem::path(config.directory) / "dead-letter";
        std::filesystem::create_directories(pendingDirectory);
        std::filesystem::create_directories(deadDirectory);
    }

    ~Impl()
    {
        stop();
    }

    void report(
        const std::string& state,
        const std::string& eventId,
        unsigned int attempts,
        const std::string& detail) noexcept
    {
        try {
            statusHandler(state, eventId, attempts, detail);
        } catch (...) {
        }
    }

    void start()
    {
        bool expected = false;
        if (!active.compare_exchange_strong(expected, true)) return;
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopRequested = false;
        }
        worker = std::thread([this] { run(); });
    }

    void stop() noexcept
    {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopRequested = true;
        }
        condition.notify_all();
        if (worker.joinable()) worker.join();
        active = false;
    }

    std::optional<std::filesystem::path> oldestPendingLocked() const
    {
        std::optional<std::filesystem::path> selected;
        std::filesystem::file_time_type selectedTime;
        for (const auto& entry : std::filesystem::directory_iterator(pendingDirectory)) {
            if (!entry.is_regular_file() || entry.path().extension() != ".json") continue;
            const auto currentTime = entry.last_write_time();
            if (!selected || currentTime < selectedTime) {
                selected = entry.path();
                selectedTime = currentTime;
            }
        }
        return selected;
    }

    Json readItem(const std::filesystem::path& path) const
    {
        std::ifstream input(path);
        if (!input.is_open()) throw std::runtime_error("Could not open Outbox item");
        Json item;
        input >> item;
        if (!item.is_object() || item.value("outbox_version", 0) != 1 ||
            !item.contains("event_id") || !item.at("event_id").is_string() ||
            !item.contains("payload") || !item.at("payload").is_string() ||
            !item.contains("attempts") || !item.at("attempts").is_number_integer() ||
            item.at("attempts").get<long long>() < 0) {
            throw std::runtime_error("Outbox item has an invalid format");
        }
        return item;
    }

    void moveToDeadLetterLocked(
        const std::filesystem::path& path,
        Json& item,
        const std::string& reason)
    {
        item["dead_letter_reason"] = reason;
        const auto destination = deadDirectory / path.filename();
        writeAtomically(destination, item);
        std::filesystem::remove(path);
    }

    bool wait(std::chrono::seconds duration)
    {
        std::unique_lock<std::mutex> lock(mutex);
        return condition.wait_for(lock, duration, [this] { return stopRequested; });
    }

    void run() noexcept
    {
        report("started", "", 0, config.directory);
        while (true) {
            std::filesystem::path path;
            Json item;
            try {
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    condition.wait(lock, [this] {
                        return stopRequested || oldestPendingLocked().has_value();
                    });
                    if (stopRequested) break;
                    path = *oldestPendingLocked();
                    item = readItem(path);
                }
            } catch (const std::exception& error) {
                report("storage_error", "", 0, error.what());
                if (wait(std::chrono::seconds(2))) break;
                continue;
            }

            const std::string eventId = item.at("event_id").get<std::string>();
            const unsigned int priorAttempts = item.at("attempts").get<unsigned int>();
            OutboxDeliveryResult result;
            try {
                result = sender(eventId, item.at("payload").get<std::string>());
            } catch (const std::exception& error) {
                result.disposition = OutboxDeliveryDisposition::RetryableFailure;
                result.detail = error.what();
            } catch (...) {
                result.disposition = OutboxDeliveryDisposition::RetryableFailure;
                result.detail = "unknown sender failure";
            }

            const unsigned int attempts = priorAttempts + 1;
            if (result.disposition == OutboxDeliveryDisposition::Delivered) {
                {
                    std::lock_guard<std::mutex> lock(mutex);
                    std::error_code ignored;
                    std::filesystem::remove(path, ignored);
                }
                report("delivered", eventId, attempts, result.detail);
                continue;
            }

            item["attempts"] = attempts;
            item["last_status_code"] = result.statusCode;
            item["last_error"] = result.detail;
            const bool exhausted = attempts >= config.maximumAttempts;
            if (result.disposition == OutboxDeliveryDisposition::PermanentFailure || exhausted) {
                try {
                    std::lock_guard<std::mutex> lock(mutex);
                    moveToDeadLetterLocked(
                        path,
                        item,
                        result.disposition == OutboxDeliveryDisposition::PermanentFailure
                            ? "permanent_failure" : "retry_exhausted");
                    report("dead_letter", eventId, attempts, result.detail);
                } catch (const std::exception& error) {
                    report("storage_error", eventId, attempts, error.what());
                }
                continue;
            }

            try {
                std::lock_guard<std::mutex> lock(mutex);
                writeAtomically(path, item);
            } catch (const std::exception& error) {
                report("storage_error", eventId, attempts, error.what());
                continue;
            }

            const auto exponential = config.initialRetryDelay * (1U << (attempts - 1));
            const auto delay = result.retryAfter.count() > 0
                ? result.retryAfter
                : std::min(exponential, config.maximumRetryDelay);
            report("retry_scheduled", eventId, attempts, result.detail);
            if (wait(delay)) break;
        }
        active = false;
        report("stopped", "", 0, "outbox stopped");
    }

    OutboxEnqueueResult enqueue(const std::string& eventId, const std::string& payload)
    {
        if (eventId.empty()) throw std::invalid_argument("Outbox event_id must not be empty");
        const Json parsedPayload = Json::parse(payload);
        if (!parsedPayload.is_object()) {
            throw std::invalid_argument("Outbox payload must be a JSON object");
        }

        std::lock_guard<std::mutex> lock(mutex);
        const auto path = pendingDirectory / stableFileName(eventId);
        if (std::filesystem::exists(path)) {
            const Json existing = readItem(path);
            if (existing.at("event_id").get<std::string>() != eventId ||
                existing.at("payload").get<std::string>() != payload) {
                throw std::runtime_error("Outbox event_id collision or conflicting payload");
            }
            return OutboxEnqueueResult::AlreadyPending;
        }
        if (jsonFileCount(pendingDirectory) >= config.maximumPending) {
            throw std::runtime_error("Decision Outbox reached its pending item limit");
        }

        const Json item{
            {"outbox_version", 1},
            {"event_id", eventId},
            {"attempts", 0},
            {"payload", payload}};
        writeAtomically(path, item);
        condition.notify_one();
        report("enqueued", eventId, 0, "persisted before delivery");
        return OutboxEnqueueResult::Enqueued;
    }
};

DecisionOutbox::DecisionOutbox(
    DecisionOutboxConfig config,
    Sender sender,
    StatusHandler statusHandler)
    : impl_(std::make_unique<Impl>(
          std::move(config), std::move(sender), std::move(statusHandler)))
{
}

DecisionOutbox::~DecisionOutbox() = default;
void DecisionOutbox::start() { impl_->start(); }
void DecisionOutbox::stop() noexcept { impl_->stop(); }

OutboxEnqueueResult DecisionOutbox::enqueue(
    const std::string& eventId,
    const std::string& payload)
{
    return impl_->enqueue(eventId, payload);
}

std::size_t DecisionOutbox::pendingCount() const
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return jsonFileCount(impl_->pendingDirectory);
}

std::size_t DecisionOutbox::deadLetterCount() const
{
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return jsonFileCount(impl_->deadDirectory);
}

const std::string& DecisionOutbox::directory() const
{
    return impl_->config.directory;
}

}
