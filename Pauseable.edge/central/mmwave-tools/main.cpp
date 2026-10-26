#include "MmWaveReceiver.hpp"
#include "MmWaveContract.hpp"
#include <chrono>
#include <csignal>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {
volatile std::sig_atomic_t stopRequested = 0;
void onSignal(int) { stopRequested = 1; }
std::uint64_t number(const std::string& value, std::uint64_t min, std::uint64_t max) {
    if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("Expected unsigned decimal integer");
    const auto parsed = std::stoull(value);
    if (parsed < min || parsed > max) throw std::invalid_argument("Argument outside allowed range");
    return parsed;
}
}
int main(int argc, char** argv) {
    try {
        pauseable::MmWaveReceiverConfig config;
        std::uint64_t duration = 0;
        std::string validatePath;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (option == "--help") {
                std::cout << "mmwave-receiver [--bind IPv4] [--port 0..65535] [--allow-peer IPv4]\n"
                    << " [--duration-ms 0..86400000] [--summary-ms 10..60000] [--stale-ms 1..3600000]\n"
                    << " [--max-pps 1..10000] [--validate FILE]\n"
                    << "Default: loopback:5005, no HA/TTS, Ctrl+C to stop; --port 0 selects a free port.\n";
                return 0;
            }
            if (i + 1 == argc) throw std::invalid_argument("Missing option value");
            const std::string value = argv[++i];
            if (option == "--bind") config.bindAddress = value;
            else if (option == "--port") config.port = static_cast<std::uint16_t>(number(value, 0, 65535));
            else if (option == "--allow-peer") config.allowPeer = value;
            else if (option == "--duration-ms") duration = number(value, 0, 86400000);
            else if (option == "--summary-ms") config.summaryEveryMs = number(value, 10, 60000);
            else if (option == "--stale-ms") config.staleAfterMs = number(value, 1, 3600000);
            else if (option == "--max-pps") config.maxPacketsPerSecond = static_cast<unsigned>(number(value, 1, 10000));
            else if (option == "--validate") validatePath = value;
            else throw std::invalid_argument("Unknown option: " + option);
        }
        if (!validatePath.empty()) {
            std::ifstream file(validatePath, std::ios::binary);
            if (!file) throw std::runtime_error("Cannot read validation input");
            std::string bytes(pauseable::kMmWaveMaxPacketBytes + 1, '\0');
            file.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
            bytes.resize(static_cast<std::size_t>(file.gcount()));
            std::cout << pauseable::parseMmWavePacket(bytes).dump() << std::endl;
            return 0;
        }
        std::signal(SIGINT, onSignal);
        std::signal(SIGTERM, onSignal);
        pauseable::MmWaveReceiver receiver(config, [](const nlohmann::json& report) {
            std::cout << report.dump() << std::endl;
        });
        receiver.start();
        const auto started = std::chrono::steady_clock::now();
        while (!stopRequested && receiver.running()) {
            if (duration && std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - started).count() >= static_cast<std::int64_t>(duration)) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        const bool healthy = receiver.running();
        receiver.stop();
        return healthy ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << nlohmann::json({{"kind", "mmwave_error"}, {"detail", error.what()}}).dump() << std::endl;
        return 1;
    }
}
