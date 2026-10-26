#include <atomic>
#include <cassert>
#include <chrono>
#include <filesystem>
#include <functional>
#include <iostream>
#include <thread>

#include "DecisionOutbox.hpp"

namespace {

bool waitUntil(const std::function<bool()>& condition, std::chrono::seconds timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (condition()) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    return condition();
}

pauseable::DecisionOutboxConfig configFor(const std::filesystem::path& directory)
{
    pauseable::DecisionOutboxConfig config;
    config.directory = directory.string();
    config.maximumPending = 10;
    config.maximumAttempts = 3;
    config.initialRetryDelay = std::chrono::seconds(1);
    config.maximumRetryDelay = std::chrono::seconds(1);
    return config;
}

}

int main()
{
    const auto root = std::filesystem::temp_directory_path() / "pauseable-decision-outbox-test";
    std::filesystem::remove_all(root);

    std::atomic<int> attempts{0};
    pauseable::DecisionOutbox outbox(
        configFor(root / "retry"),
        [&attempts](const std::string&, const std::string&) {
            const int current = ++attempts;
            return pauseable::OutboxDeliveryResult{
                current == 1
                    ? pauseable::OutboxDeliveryDisposition::RetryableFailure
                    : pauseable::OutboxDeliveryDisposition::Delivered,
                current == 1 ? 503 : 202,
                current == 1 ? "temporary" : "accepted",
                std::chrono::seconds(0)};
        },
        [](const std::string&, const std::string&, unsigned int, const std::string&) {});

    assert(outbox.enqueue("evt-outbox-1", "{\"event_id\":\"evt-outbox-1\"}") ==
           pauseable::OutboxEnqueueResult::Enqueued);
    assert(outbox.enqueue("evt-outbox-1", "{\"event_id\":\"evt-outbox-1\"}") ==
           pauseable::OutboxEnqueueResult::AlreadyPending);
    assert(outbox.pendingCount() == 1);
    outbox.start();
    assert(waitUntil([&outbox] { return outbox.pendingCount() == 0; }, std::chrono::seconds(4)));
    outbox.stop();
    assert(attempts == 2);
    assert(outbox.deadLetterCount() == 0);

    pauseable::DecisionOutbox permanent(
        configFor(root / "permanent"),
        [](const std::string&, const std::string&) {
            return pauseable::OutboxDeliveryResult{
                pauseable::OutboxDeliveryDisposition::PermanentFailure,
                422,
                "schema rejected",
                std::chrono::seconds(0)};
        },
        [](const std::string&, const std::string&, unsigned int, const std::string&) {});
    permanent.enqueue("evt-outbox-2", "{\"event_id\":\"evt-outbox-2\"}");
    permanent.start();
    assert(waitUntil(
        [&permanent] { return permanent.deadLetterCount() == 1; },
        std::chrono::seconds(2)));
    permanent.stop();
    assert(permanent.pendingCount() == 0);

    std::filesystem::remove_all(root);
    std::cout << "decision_outbox_test passed\n";
    return 0;
}
