#include "MmWaveArchive.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cctype>
#include <ctime>
#include <deque>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <map>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace pauseable {
namespace {

constexpr std::uintmax_t kMaxArchiveFileBytes = 4ULL * 1024ULL * 1024ULL;

std::tm utcTime(std::time_t value) {
    std::tm result {};
    gmtime_r(&value, &result);
    return result;
}

std::string utcNow() {
    const auto now = std::chrono::system_clock::now();
    const auto rawTime = std::chrono::system_clock::to_time_t(now);
    const auto utc = utcTime(rawTime);

    std::ostringstream output;
    output << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return output.str();
}

std::string utcDay() {
    const auto rawTime = std::chrono::system_clock::to_time_t(
        std::chrono::system_clock::now());
    const auto utc = utcTime(rawTime);

    std::ostringstream output;
    output << std::put_time(&utc, "%Y%m%d");
    return output.str();
}

bool isArchiveFileName(const std::string& name) {
    const std::string prefix = "mmwave-";
    const std::string suffix = ".jsonl";

    if (name.rfind(prefix, 0) != 0 ||
        name.size() <= prefix.size() + suffix.size() ||
        name.substr(name.size() - suffix.size()) != suffix) {
        return false;
    }

    const std::string stem = name.substr(
        prefix.size(),
        name.size() - prefix.size() - suffix.size());

    if (stem.size() < 8) {
        return false;
    }

    for (std::size_t index = 0; index < 8; ++index) {
        if (!std::isdigit(static_cast<unsigned char>(stem[index]))) {
            return false;
        }
    }

    if (stem.size() == 8) {
        return true;
    }

    if (stem[8] != '-' || stem.size() == 9) {
        return false;
    }

    for (std::size_t index = 9; index < stem.size(); ++index) {
        if (!std::isdigit(static_cast<unsigned char>(stem[index]))) {
            return false;
        }
    }

    return true;
}

std::string timestampFor(const nlohmann::json& report) {
    const auto timestamp = report.value("received_at", std::string {});
    return timestamp.empty() ? utcNow() : timestamp;
}

std::string streamKey(
    const std::string& dataOrigin,
    const std::string& sensorId) {
    return dataOrigin + ":" + sensorId;
}

}

struct MmWaveArchive::Impl {
    struct ArchiveFile {
        std::filesystem::path path;
        std::uintmax_t size;
        std::filesystem::file_time_type modified;
    };

    explicit Impl(MmWaveArchiveConfig archiveConfig, Reporter archiveReporter)
        : config(std::move(archiveConfig)),
          reporter(std::move(archiveReporter)) {}

    ~Impl() {
        stop();
    }

    void start() {
        validateStorage();

        {
            std::lock_guard<std::mutex> lock(mutex);

            if (accepting) {
                return;
            }

            if (stopping) {
                throw std::runtime_error(
                    "mmWave archive is currently stopping");
            }

            accepting = true;
            stopping = false;
            writer = std::thread(&Impl::writerLoop, this);
        }

        emit({
            {"kind", "mmwave_archive_ready"},
            {"directory", config.directory},
            {"sample_every_ms", config.sampleEveryMs},
            {"max_total_bytes", config.maxTotalBytes},
            {"max_retention_days", config.maxRetentionDays},
        });
    }

    void submit(const nlohmann::json& receiverReport) noexcept {
        try {
            std::size_t queuedRecords = 0;

            {
                std::lock_guard<std::mutex> lock(mutex);

                if (!accepting) {
                    return;
                }

                auto records = makeRecordsLocked(receiverReport);

                for (auto& record : records) {
                    if (queue.size() >= config.maxQueuedRecords) {
                        ++droppedRecords;
                        continue;
                    }

                    queue.push_back(std::move(record));
                    ++queuedRecords;
                }
            }

            if (queuedRecords > 0) {
                wakeWriter.notify_one();
            }
        } catch (...) {

        }
    }

    void stop() noexcept {
        std::thread writerToJoin;

        {
            std::lock_guard<std::mutex> lock(mutex);

            if (!writer.joinable()) {
                accepting = false;
                return;
            }

            accepting = false;
            stopping = true;
            writerToJoin = std::move(writer);
        }

        wakeWriter.notify_all();
        writerToJoin.join();

        {
            std::lock_guard<std::mutex> lock(mutex);
            stopping = false;
            queue.clear();
        }

        emit({
            {"kind", "mmwave_archive_stopped"},
            {"written_records", writtenRecords},
            {"dropped_records", droppedRecords},
            {"io_errors", ioErrors},
        });
    }

    bool running() const noexcept {
        std::lock_guard<std::mutex> lock(mutex);
        return accepting;
    }

    MmWaveArchiveConfig config;
    Reporter reporter;

    mutable std::mutex mutex;
    std::condition_variable wakeWriter;
    std::deque<nlohmann::json> queue;
    std::thread writer;

    bool accepting = false;
    bool stopping = false;

    std::uint64_t writtenRecords = 0;
    std::uint64_t droppedRecords = 0;
    std::uint64_t ioErrors = 0;

    std::map<std::string, std::uint64_t> lastSampleMonoMs;
    std::map<std::string, std::string> lastQualityState;

    std::filesystem::path activePath;
    std::string activeDay;
    std::chrono::steady_clock::time_point lastErrorNotice {};

    void validateStorage() const {
        const std::filesystem::path directory(config.directory);
        std::error_code error;

        if (config.directory.empty() ||
            !std::filesystem::exists(directory, error) ||
            error) {
            throw std::runtime_error(
                "mmWave archive directory does not exist: " +
                config.directory);
        }

        if (!std::filesystem::is_directory(directory, error) || error) {
            throw std::runtime_error(
                "mmWave archive path is not a directory: " +
                config.directory);
        }
    }

    void emit(const nlohmann::json& report) const noexcept {
        if (!reporter) {
            return;
        }

        try {
            reporter(report);
        } catch (...) {
        }
    }

    void emitIoError(const std::string& message) noexcept {
        ++ioErrors;

        const auto now = std::chrono::steady_clock::now();
        if (lastErrorNotice.time_since_epoch().count() != 0 &&
            now - lastErrorNotice < std::chrono::seconds(60)) {
            return;
        }

        lastErrorNotice = now;

        emit({
            {"kind", "mmwave_archive_error"},
            {"message", message},
            {"io_errors", ioErrors},
        });
    }

    std::vector<nlohmann::json> makeRecordsLocked(
        const nlohmann::json& report) {
        std::vector<nlohmann::json> records;
        const std::string kind = report.value("kind", std::string {});

        if (kind == "mmwave_rejected" ||
            (kind == "mmwave_event" &&
             !report.value("accepted", false))) {
            records.push_back({
                {"archive_schema_version", "1.0"},
                {"record_type", "rejected_metadata"},
                {"recorded_at", timestampFor(report)},
                {"reason", report.value("reason", std::string {"unknown"})},
                {"peer", report.value("peer", std::string {})},
            });
            return records;
        }

        if (kind == "mmwave_event") {
            const auto eventIt = report.find("event");
            if (eventIt == report.end() || !eventIt->is_object()) {
                return records;
            }

            const auto& event = *eventIt;
            const std::string dataOrigin = event.value(
                "data_origin",
                report.value("data_origin", std::string {"unknown"}));
            const std::string sensorId = event.value(
                "sensor_id",
                report.value("sensor_id", std::string {"unknown"}));
            const std::string key = streamKey(dataOrigin, sensorId);

            const auto receivedMonoMs = report.value(
                "received_mono_ms",
                std::uint64_t {0});
            const bool sensorError =
                event.value("sensor_status", std::string {"unknown"}) != "ok";
            const bool important =
                sensorError ||
                report.value("new_stream", false) ||
                report.value("session_changed", false);

            const auto previous = lastSampleMonoMs.find(key);
            const bool intervalElapsed =
                previous == lastSampleMonoMs.end() ||
                receivedMonoMs == 0 ||
                receivedMonoMs < previous->second ||
                receivedMonoMs - previous->second >= config.sampleEveryMs;

            if (!important && !intervalElapsed) {
                return records;
            }

            lastSampleMonoMs[key] = receivedMonoMs;

            nlohmann::json record = {
                {"archive_schema_version", "1.0"},
                {"record_type", "accepted_sample"},
                {"recorded_at", timestampFor(report)},
                {"data_origin", dataOrigin},
                {"sensor_id", sensorId},
                {"event", event},
                {"receiver", {
                    {"peer", report.value("peer", std::string {})},
                    {"received_at", timestampFor(report)},
                    {"received_mono_ms", receivedMonoMs},
                    {"new_stream", report.value("new_stream", false)},
                    {"session_changed", report.value("session_changed", false)},
                }},
            };

            records.push_back(std::move(record));
            return records;
        }

        if (kind == "mmwave_summary" || kind == "mmwave_stopped") {
            const auto streamsIt = report.find("streams");
            if (streamsIt == report.end() || !streamsIt->is_array()) {
                return records;
            }

            for (const auto& stream : *streamsIt) {
                if (!stream.is_object()) {
                    continue;
                }

                const std::string dataOrigin = stream.value(
                    "data_origin",
                    std::string {"unknown"});
                const std::string sensorId = stream.value(
                    "sensor_id",
                    std::string {"unknown"});
                const std::string quality = stream.value(
                    "quality",
                    std::string {"unknown"});
                const std::string observation = stream.value(
                    "observation",
                    std::string {"unknown"});
                const std::string key = streamKey(dataOrigin, sensorId);
                const std::string nextState = quality + "|" + observation;

                const auto previous = lastQualityState.find(key);
                if (previous != lastQualityState.end() &&
                    previous->second == nextState) {
                    continue;
                }

                lastQualityState[key] = nextState;

                nlohmann::json state = {
                    {"data_origin", dataOrigin},
                    {"sensor_id", sensorId},
                    {"session_id", stream.value("session_id", std::string {})},
                    {"quality", quality},
                    {"observation", observation},
                };

                if (stream.contains("effective_frame_age_ms")) {
                    state["effective_frame_age_ms"] =
                        stream["effective_frame_age_ms"];
                }

                if (stream.contains("receiver_age_ms")) {
                    state["receiver_age_ms"] = stream["receiver_age_ms"];
                }

                records.push_back({
                    {"archive_schema_version", "1.0"},
                    {"record_type", "quality_transition"},
                    {"recorded_at", timestampFor(report)},
                    {"state", std::move(state)},
                });
            }

            return records;
        }

        if (kind == "mmwave_error") {
            records.push_back({
                {"archive_schema_version", "1.0"},
                {"record_type", "receiver_error"},
                {"recorded_at", timestampFor(report)},
                {"message", report.value(
                    "detail",
                    report.value("message", std::string {"unknown"}))},
            });
        }

        return records;
    }

    void writerLoop() noexcept {
        try {
            while (true) {
                nlohmann::json record;

                {
                    std::unique_lock<std::mutex> lock(mutex);
                    wakeWriter.wait(lock, [this] {
                        return stopping || !queue.empty();
                    });

                    if (queue.empty()) {
                        if (stopping) {
                            break;
                        }
                        continue;
                    }

                    record = std::move(queue.front());
                    queue.pop_front();
                }

                writeRecord(record);
            }
        } catch (const std::exception& error) {
            emitIoError(error.what());
        } catch (...) {
            emitIoError("unknown mmWave archive worker error");
        }
    }

    std::uintmax_t fileSize(const std::filesystem::path& path) const {
        std::error_code error;
        const auto size = std::filesystem::file_size(path, error);
        return error ? 0 : size;
    }

    std::filesystem::path selectOutputPath() {
        const std::string today = utcDay();

        if (activeDay != today) {
            activeDay = today;
            activePath.clear();
        }

        if (!activePath.empty() &&
            fileSize(activePath) < kMaxArchiveFileBytes) {
            return activePath;
        }

        for (unsigned int index = 0; index < 10000; ++index) {
            std::ostringstream name;
            name << "mmwave-" << today;

            if (index > 0) {
                name << "-" << std::setw(3) << std::setfill('0') << index;
            }

            name << ".jsonl";

            const auto candidate =
                std::filesystem::path(config.directory) / name.str();

            if (!std::filesystem::exists(candidate) ||
                fileSize(candidate) < kMaxArchiveFileBytes) {
                activePath = candidate;
                return activePath;
            }
        }

        throw std::runtime_error(
            "could not allocate a new mmWave archive file");
    }

    void prune() {
        std::error_code error;
        const auto cutoff =
            std::filesystem::file_time_type::clock::now() -
            std::chrono::hours(
                24 * static_cast<int>(config.maxRetentionDays));

        std::vector<ArchiveFile> files;
        std::filesystem::directory_iterator iterator(
            std::filesystem::path(config.directory),
            error);

        for (; !error && iterator != std::filesystem::directory_iterator {};
             iterator.increment(error)) {
            const auto& entry = *iterator;
            const auto name = entry.path().filename().string();

            if (!isArchiveFileName(name)) {
                continue;
            }

            std::error_code entryError;
            if (!entry.is_regular_file(entryError) || entryError) {
                continue;
            }

            const auto modified = entry.last_write_time(entryError);
            if (entryError) {
                continue;
            }

            const auto size = entry.file_size(entryError);
            if (entryError) {
                continue;
            }

            if (modified < cutoff) {
                std::error_code removeError;
                std::filesystem::remove(entry.path(), removeError);
                continue;
            }

            files.push_back({
                entry.path(),
                size,
                modified,
            });
        }

        std::sort(
            files.begin(),
            files.end(),
            [](const ArchiveFile& left, const ArchiveFile& right) {
                return left.modified < right.modified;
            });

        std::uintmax_t totalBytes = 0;
        for (const auto& file : files) {
            totalBytes += file.size;
        }

        for (const auto& file : files) {
            if (totalBytes <= config.maxTotalBytes) {
                break;
            }

            if (file.path == activePath && files.size() == 1) {
                break;
            }

            std::error_code removeError;
            if (std::filesystem::remove(file.path, removeError)) {
                totalBytes -= file.size;
            }
        }
    }

    void writeRecord(const nlohmann::json& record) noexcept {
        try {
            const auto outputPath = selectOutputPath();

            std::ofstream output(
                outputPath,
                std::ios::out | std::ios::app);

            if (!output.is_open()) {
                throw std::runtime_error(
                    "could not open mmWave archive file");
            }

            output << record.dump() << '\n';
            output.flush();

            if (!output.good()) {
                throw std::runtime_error(
                    "could not write mmWave archive record");
            }

            ++writtenRecords;
            prune();
        } catch (const std::exception& error) {
            emitIoError(error.what());
        } catch (...) {
            emitIoError("unknown mmWave archive write error");
        }
    }
};

MmWaveArchive::MmWaveArchive(
    MmWaveArchiveConfig config,
    Reporter reporter)
    : impl_(std::make_unique<Impl>(
          std::move(config),
          std::move(reporter))) {}

MmWaveArchive::~MmWaveArchive() = default;

void MmWaveArchive::start() {
    impl_->start();
}

void MmWaveArchive::submit(
    const nlohmann::json& receiverReport) noexcept {
    impl_->submit(receiverReport);
}

void MmWaveArchive::stop() noexcept {
    impl_->stop();
}

bool MmWaveArchive::running() const noexcept {
    return impl_->running();
}

}
