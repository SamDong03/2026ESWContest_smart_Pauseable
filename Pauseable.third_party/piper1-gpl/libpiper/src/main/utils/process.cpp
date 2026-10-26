#include "process.hpp"
#include "wavfile.hpp"
#include "json.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

using json = nlohmann::json;

void processInputStream(piper::RunConfig &runConfig, piper_synthesizer *piper, piper_synthesize_options *options) {

    std::string line;
    while (getline(std::cin, line)) {
        if (line.empty()) {
            continue;
        }

        piper_synthesize_options local_options = *options;
        auto outputType = runConfig.outputType;
        std::optional<std::filesystem::path> maybeOutputPath = runConfig.outputPath;

        if (runConfig.jsonInput) {

            json lineRoot = json::parse(line);


            line = lineRoot["text"].get<std::string>();

            if (lineRoot.contains("output_file")) {

                outputType = piper::OUTPUT_FILE;
                maybeOutputPath =
                    std::filesystem::path(lineRoot["output_file"].get<std::string>());
            }

            if (lineRoot.contains("speaker_id")) {

                local_options.speaker_id =
                    lineRoot["speaker_id"].get<int>();
            }
        }


        const auto now = std::chrono::system_clock::now();
        const auto timestamp =
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch())
            .count();
        if (outputType == piper::OUTPUT_DIRECTORY) {

            std::stringstream outputName;
            outputName << timestamp << ".wav";
            std::filesystem::path outputPath = runConfig.outputPath.value();
            outputPath.append(outputName.str());
            {

                std::ofstream audioFile(outputPath.string(), std::ios::binary);
                textToWavFile(piper, &local_options, line.c_str(), audioFile);
            }
            std::cout << outputPath.string() << std::endl;
        } else if (outputType == piper::OUTPUT_FILE) {
            if (!maybeOutputPath || maybeOutputPath->empty()) {
                throw std::runtime_error("No output path provided");
            }
            std::filesystem::path outputPath = maybeOutputPath.value();

            if (!runConfig.jsonInput) {


                std::stringstream text;
                text << line;
                while (getline(std::cin, line)) {
                    text << " " << line;
                }

                line = text.str();
            }
            {

                std::ofstream audioFile(outputPath.string(), std::ios::binary);
                textToWavFile(piper, &local_options, line.c_str(), audioFile);
            }
            std::cout << outputPath.string() << std::endl;
        } else if (outputType == piper::OUTPUT_STDOUT) {

            textToWavFile(piper, &local_options, line.c_str(), std::cout);
        }
    }
}
