#pragma once

#include <string>
#include <memory>
#include <filesystem>

class PiperTestAssets {
public:

    explicit PiperTestAssets(std::filesystem::path modelDir);


    ~PiperTestAssets() = default;


    std::filesystem::path modelPath() const;

    std::filesystem::path configPath() const;

    static std::filesystem::path espeakDataPath();


    static std::unique_ptr<PiperTestAssets> enModel();

private:
    std::filesystem::path modelDir;
};
