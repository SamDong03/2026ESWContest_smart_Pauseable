#include "MmWaveArchive.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using nlohmann::json;

#define CHECK(expression)                                                        \
    do {                                                                         \
        if (!(expression)) {                                                     \
            throw std::runtime_error(std::string("line ") +                     \
                                     std::to_string(__LINE__) + ": " #expression); \
        }                                                                        \
    } while (false)

struct TemporaryDirectory {
    std::filesystem::path path;

    TemporaryDirectory()
    {
        const auto suffix = std::chrono::steady_clock::now()
                                .time_since_epoch()
                                .count();
        path = std::filesystem::temp_directory_path() /
               ("pauseable-mmwave-archive-test-" + std::to_string(suffix));
        std::filesystem::create_directories(path);
    }

    ~TemporaryDirectory()
    {
        std::error_code error;
        std::filesystem::remove_all(path, error);
    }
};

std::vector<json> loadRecords(const std::filesystem::path& directory)
{
    std::vector<json> records;

    for (const auto& entry : std::filesystem::directory_iterator(directory)) {
        if (!entry.is_regular_file() || entry.path().extension() != ".jsonl") {
            continue;
        }

        std::ifstream input(entry.path());
        std::string line;
        while (std::getline(input, line)) {
            if (!line.empty()) {
                records.push_back(json::parse(line));
            }
        }
    }

    return records;
}

const json& recordOfType(
    const std::vector<json>& records,
    const std::string& type)
{
    for (const auto& record : records) {
        if (record.value("record_type", std::string {}) == type) {
            return record;
        }
    }

    throw std::runtime_error("missing archive record type: " + type);
}

void receiverReportsUseTheirActualFieldNames()
{
    TemporaryDirectory temporary;
    std::vector<json> reporterMessages;

    pauseable::MmWaveArchiveConfig config;
    config.directory = temporary.path.string();
    config.sampleEveryMs = 1;
    config.maxTotalBytes = 1024 * 1024;
    config.maxRetentionDays = 1;
    config.maxQueuedRecords = 16;

    pauseable::MmWaveArchive archive(
        config,
        [&reporterMessages](const json& report) {
            reporterMessages.push_back(report);
        });

    archive.start();
    archive.submit({
        {"kind", "mmwave_rejected"},
        {"accepted", false},
        {"reason", "duplicate"},
        {"peer", "127.0.0.1:5006"},
        {"received_at", "2026-09-18T00:00:00Z"},
    });
    archive.submit({
        {"kind", "mmwave_error"},
        {"detail", "UDP receive failed"},
        {"received_at", "2026-09-18T00:00:01Z"},
    });
    archive.stop();

    const auto records = loadRecords(temporary.path);
    CHECK(records.size() == 2);

    const auto& rejected = recordOfType(records, "rejected_metadata");
    CHECK(rejected.at("reason") == "duplicate");
    CHECK(rejected.at("peer") == "127.0.0.1:5006");

    const auto& error = recordOfType(records, "receiver_error");
    CHECK(error.at("message") == "UDP receive failed");

    CHECK(!reporterMessages.empty());
    CHECK(reporterMessages.front().at("kind") == "mmwave_archive_ready");
    CHECK(reporterMessages.back().at("kind") == "mmwave_archive_stopped");
}

}

int main()
{
    try {
        receiverReportsUseTheirActualFieldNames();
        std::cout << "MmWave archive: 1/1 passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "MmWave archive FAIL: " << error.what() << '\n';
        return 1;
    }
}
