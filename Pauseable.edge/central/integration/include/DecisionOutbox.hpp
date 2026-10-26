#pragma once

#include <atomic>
#include <chrono>
#include <cstddef>
#include <functional>
#include <memory>
#include <string>

namespace pauseable {

enum class OutboxDeliveryDisposition {
    Delivered,
    RetryableFailure,
    PermanentFailure
};

struct OutboxDeliveryResult {
    OutboxDeliveryDisposition disposition{OutboxDeliveryDisposition::RetryableFailure};
    int statusCode{0};
    std::string detail;
    std::chrono::seconds retryAfter{0};
};

enum class OutboxEnqueueResult {
    Enqueued,
    AlreadyPending
};

struct DecisionOutboxConfig {
    std::string directory;
    std::size_t maximumPending{10000};
    unsigned int maximumAttempts{3};
    std::chrono::seconds initialRetryDelay{1};
    std::chrono::seconds maximumRetryDelay{4};
};

class DecisionOutbox {
public:
    using Sender = std::function<OutboxDeliveryResult(
        const std::string& eventId,
        const std::string& payload)>;
    using StatusHandler = std::function<void(
        const std::string& state,
        const std::string& eventId,
        unsigned int attempts,
        const std::string& detail)>;

    DecisionOutbox(
        DecisionOutboxConfig config,
        Sender sender,
        StatusHandler statusHandler);
    ~DecisionOutbox();

    DecisionOutbox(const DecisionOutbox&) = delete;
    DecisionOutbox& operator=(const DecisionOutbox&) = delete;

    void start();
    void stop() noexcept;
    OutboxEnqueueResult enqueue(const std::string& eventId, const std::string& payload);
    std::size_t pendingCount() const;
    std::size_t deadLetterCount() const;
    const std::string& directory() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}
