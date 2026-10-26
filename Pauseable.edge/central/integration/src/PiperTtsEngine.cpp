#include "PiperTtsEngine.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <alog.hpp>

namespace pauseable {
namespace {

constexpr std::size_t kMaximumQueuedMessages = 4;

std::uint16_t readLittleEndian16(const std::vector<std::uint8_t>& bytes, std::size_t offset)
{
    return static_cast<std::uint16_t>(bytes.at(offset)) |
        (static_cast<std::uint16_t>(bytes.at(offset + 1)) << 8U);
}

std::uint32_t readLittleEndian32(const std::vector<std::uint8_t>& bytes, std::size_t offset)
{
    return static_cast<std::uint32_t>(bytes.at(offset)) |
        (static_cast<std::uint32_t>(bytes.at(offset + 1)) << 8U) |
        (static_cast<std::uint32_t>(bytes.at(offset + 2)) << 16U) |
        (static_cast<std::uint32_t>(bytes.at(offset + 3)) << 24U);
}

bool chunkIdEquals(
    const std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    const char expected[5]
)
{
    return offset + 4 <= bytes.size() &&
        std::memcmp(bytes.data() + offset, expected, 4) == 0;
}

void amplifyWav(
    const std::string& inputPath,
    const std::string& outputPath,
    double gain
)
{
    std::ifstream input(inputPath, std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error("Could not open generated WAV: " + inputPath);
    }

    std::vector<std::uint8_t> bytes{
        std::istreambuf_iterator<char>(input),
        std::istreambuf_iterator<char>()
    };
    if (bytes.size() < 12 || !chunkIdEquals(bytes, 0, "RIFF") ||
        !chunkIdEquals(bytes, 8, "WAVE")) {
        throw std::runtime_error("Piper output is not a RIFF/WAVE file");
    }

    std::uint16_t audioFormat = 0;
    std::uint16_t bitsPerSample = 0;
    std::size_t dataOffset = 0;
    std::size_t dataSize = 0;

    for (std::size_t chunkOffset = 12; chunkOffset + 8 <= bytes.size();) {
        const std::uint32_t chunkSize = readLittleEndian32(bytes, chunkOffset + 4);
        const std::size_t chunkDataOffset = chunkOffset + 8;
        const std::size_t availableSize = bytes.size() - chunkDataOffset;

        if (chunkIdEquals(bytes, chunkOffset, "fmt ") && chunkSize >= 16) {
            if (chunkSize > availableSize) {
                throw std::runtime_error("Generated WAV contains an invalid fmt chunk size");
            }
            audioFormat = readLittleEndian16(bytes, chunkDataOffset);
            bitsPerSample = readLittleEndian16(bytes, chunkDataOffset + 14);
        } else if (chunkIdEquals(bytes, chunkOffset, "data")) {
            dataOffset = chunkDataOffset;


            dataSize = std::min<std::size_t>(chunkSize, availableSize);
            break;
        } else if (chunkSize > availableSize) {
            throw std::runtime_error("Generated WAV contains an invalid chunk size");
        }

        chunkOffset = chunkDataOffset + chunkSize + (chunkSize & 1U);
    }

    const bool pcm16 = audioFormat == 1 && bitsPerSample == 16;
    const bool float32 = audioFormat == 3 && bitsPerSample == 32;
    if ((!pcm16 && !float32) || dataOffset == 0) {
        throw std::runtime_error(
            "Only 16-bit PCM and 32-bit IEEE float Piper WAV output are supported"
        );
    }

    if (pcm16) {
        const std::size_t dataEnd = dataOffset + (dataSize & ~std::size_t{1});
        for (std::size_t offset = dataOffset; offset < dataEnd; offset += 2) {
            const auto raw = readLittleEndian16(bytes, offset);
            const auto sample = static_cast<std::int16_t>(raw);
            const long amplified = std::lround(static_cast<double>(sample) * gain);
            const auto clipped = static_cast<std::int16_t>(
                std::clamp(amplified, -32768L, 32767L)
            );
            const auto encoded = static_cast<std::uint16_t>(clipped);
            bytes[offset] = static_cast<std::uint8_t>(encoded & 0xffU);
            bytes[offset + 1] = static_cast<std::uint8_t>((encoded >> 8U) & 0xffU);
        }
    } else {
        static_assert(sizeof(float) == 4, "Piper float WAV support requires 32-bit float");
        const std::size_t dataEnd = dataOffset + (dataSize & ~std::size_t{3});
        for (std::size_t offset = dataOffset; offset < dataEnd; offset += 4) {
            const std::uint32_t encodedSample = readLittleEndian32(bytes, offset);
            float sample = 0.0F;
            std::memcpy(&sample, &encodedSample, sizeof(sample));

            const float amplified = std::clamp(
                sample * static_cast<float>(gain),
                -1.0F,
                1.0F
            );
            std::uint32_t encodedAmplified = 0;
            std::memcpy(&encodedAmplified, &amplified, sizeof(encodedAmplified));
            bytes[offset] = static_cast<std::uint8_t>(encodedAmplified & 0xffU);
            bytes[offset + 1] =
                static_cast<std::uint8_t>((encodedAmplified >> 8U) & 0xffU);
            bytes[offset + 2] =
                static_cast<std::uint8_t>((encodedAmplified >> 16U) & 0xffU);
            bytes[offset + 3] =
                static_cast<std::uint8_t>((encodedAmplified >> 24U) & 0xffU);
        }
    }

    const std::string temporaryPath = outputPath + ".tmp";
    std::ofstream output(temporaryPath, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        throw std::runtime_error("Could not create amplified WAV: " + temporaryPath);
    }
    output.write(
        reinterpret_cast<const char*>(bytes.data()),
        static_cast<std::streamsize>(bytes.size())
    );
    output.close();
    if (!output) {
        std::remove(temporaryPath.c_str());
        throw std::runtime_error("Could not finish writing amplified WAV");
    }

    if (std::rename(temporaryPath.c_str(), outputPath.c_str()) != 0) {
        const std::string reason = std::strerror(errno);
        std::remove(temporaryPath.c_str());
        throw std::runtime_error("Could not publish amplified WAV: " + reason);
    }
}

int runProcess(const std::vector<std::string>& arguments, const std::string* stdinPath = nullptr)
{
    if (arguments.empty()) {
        throw std::invalid_argument("A process executable is required");
    }

    std::vector<char*> argv;
    argv.reserve(arguments.size() + 1);
    for (const auto& argument : arguments) {
        argv.push_back(const_cast<char*>(argument.c_str()));
    }
    argv.push_back(nullptr);

    const pid_t child = fork();
    if (child < 0) {
        throw std::runtime_error("fork failed: " + std::string(std::strerror(errno)));
    }

    if (child == 0) {
        if (stdinPath != nullptr) {
            const int inputDescriptor = open(stdinPath->c_str(), O_RDONLY);
            if (inputDescriptor < 0 || dup2(inputDescriptor, STDIN_FILENO) < 0) {
                _exit(126);
            }
            close(inputDescriptor);
        }

        execv(argv.front(), argv.data());
        _exit(127);
    }

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) {
            throw std::runtime_error("waitpid failed: " + std::string(std::strerror(errno)));
        }
    }

    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
}

void requireReadablePath(const std::string& path, const char* description)
{
    if (access(path.c_str(), R_OK) != 0) {
        throw std::runtime_error(std::string(description) + " is unavailable: " + path);
    }
}

}

PiperTtsEngine::PiperTtsEngine(
    std::string bundleRoot,
    std::string outputWavPath,
    double gain
)
    : bundleRoot_(std::move(bundleRoot)),
      outputWavPath_(std::move(outputWavPath)),
      gain_(gain)
{
    if (!(gain_ > 0.0 && gain_ <= 10.0)) {
        throw std::invalid_argument("TTS gain must be greater than 0 and at most 10");
    }

    requireReadablePath(bundleRoot_ + "/bin/piper", "Piper executable");
    requireReadablePath(
        bundleRoot_ + "/models/ko_KR-guardian-medium.onnx",
        "Piper model"
    );
    requireReadablePath(
        bundleRoot_ + "/models/ko_KR-guardian-medium.onnx.json",
        "Piper model config"
    );
    requireReadablePath(bundleRoot_ + "/share/espeak-ng-data", "eSpeak data");

    worker_ = std::thread(&PiperTtsEngine::workerLoop, this);
}

PiperTtsEngine::~PiperTtsEngine()
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stopping_ = true;
        messages_.clear();
    }
    condition_.notify_one();
    if (worker_.joinable()) {
        worker_.join();
    }
}

void PiperTtsEngine::speak(
    std::string message,
    CompletionHandler onCompleted
)
{
    if (message.empty()) {
        return;
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stopping_) {
            return;
        }
        if (messages_.size() >= kMaximumQueuedMessages) {
            messages_.pop_front();
            alog::logWarn("TTS_QUEUE_FULL", "Dropped the oldest queued TTS message");
        }
        messages_.push_back({
            std::move(message),
            std::move(onCompleted)
        });
    }

    condition_.notify_one();
    alog::logInfo("TTS_QUEUED", "Queued a local Piper TTS message");
}

void PiperTtsEngine::workerLoop()
{
    while (true) {
        QueuedMessage message;

        {
            std::unique_lock<std::mutex> lock(mutex_);
            condition_.wait(lock, [this] {
                return stopping_ || !messages_.empty();
            });

            if (stopping_) {
                return;
            }

            message = std::move(messages_.front());
            messages_.pop_front();
        }

        try {
            synthesizeAndPlay(message.text);
            alog::logInfo(
                "TTS_COMPLETED",
                "Piper synthesis and playback completed"
            );
        } catch (const std::exception& error) {
            alog::logError(
                "TTS_FAILED",
                "Local Piper TTS failed: {}",
                error.what()
            );
            continue;
        }

        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (stopping_) {
                return;
            }
        }

        if (message.onCompleted) {
            try {
                message.onCompleted();
            } catch (const std::exception& error) {
                alog::logError(
                    "TTS_COMPLETION_HANDLER_FAILED",
                    "Post-playback action failed: {}",
                    error.what()
                );
            } catch (...) {
                alog::logError(
                    "TTS_COMPLETION_HANDLER_FAILED",
                    "Post-playback action failed with an unknown exception"
                );
            }
        }
    }
}

void PiperTtsEngine::synthesizeAndPlay(const std::string& message) const
{
    const std::string inputPath = outputWavPath_ + ".input.txt";
    const std::string generatedPath = outputWavPath_ + ".generated.wav";
    {
        std::ofstream input(inputPath, std::ios::binary | std::ios::trunc);
        if (!input.is_open()) {
            throw std::runtime_error("Could not create Piper input text: " + inputPath);
        }
        input << message << '\n';
        if (!input) {
            throw std::runtime_error("Could not write Piper input text");
        }
    }

    std::remove(generatedPath.c_str());
    const std::string piperExecutable = bundleRoot_ + "/bin/piper";
    const std::vector<std::string> piperArguments{
        "/usr/bin/env",
        "LD_LIBRARY_PATH=" + bundleRoot_ + "/lib:/usr/lib",
        piperExecutable,
        "--model",
        bundleRoot_ + "/models/ko_KR-guardian-medium.onnx",
        "--config",
        bundleRoot_ + "/models/ko_KR-guardian-medium.onnx.json",
        "--espeak_data",
        bundleRoot_ + "/share/espeak-ng-data",
        "--output_file",
        generatedPath,
    };

    const int piperExitCode = runProcess(piperArguments, &inputPath);
    std::remove(inputPath.c_str());
    if (piperExitCode != 0) {
        throw std::runtime_error("Piper exited with code " + std::to_string(piperExitCode));
    }

    amplifyWav(generatedPath, outputWavPath_, gain_);
    std::remove(generatedPath.c_str());

    const std::string bundledAudioPlayer = bundleRoot_ + "/bin/paplay";
    const std::string audioPlayer = access(bundledAudioPlayer.c_str(), X_OK) == 0
        ? bundledAudioPlayer
        : "/usr/bin/paplay";
    const int playbackExitCode = runProcess({audioPlayer, outputWavPath_});
    if (playbackExitCode != 0) {
        throw std::runtime_error(
            "Audio player exited with code " + std::to_string(playbackExitCode)
        );
    }
}

}
