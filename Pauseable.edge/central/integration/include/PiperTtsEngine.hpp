#pragma once

#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

namespace pauseable {

class PiperTtsEngine
{
public:
    using CompletionHandler = std::function<void()>;

    PiperTtsEngine(std::string bundleRoot, std::string outputWavPath, double gain);
    ~PiperTtsEngine();

    PiperTtsEngine(const PiperTtsEngine&) = delete;
    PiperTtsEngine& operator=(const PiperTtsEngine&) = delete;

    void speak(std::string message, CompletionHandler onCompleted = {});

private:
    struct QueuedMessage {
        std::string text;
        CompletionHandler onCompleted;
    };

    void workerLoop();
    void synthesizeAndPlay(const std::string& message) const;

    std::string bundleRoot_;
    std::string outputWavPath_;
    double gain_;

    std::mutex mutex_;
    std::condition_variable condition_;
    std::deque<QueuedMessage> messages_;
    bool stopping_{false};
    std::thread worker_;
};

}
