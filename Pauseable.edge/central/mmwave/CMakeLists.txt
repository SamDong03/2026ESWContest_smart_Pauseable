cmake_minimum_required(VERSION 3.14)
find_package(Threads REQUIRED)
get_filename_component(PAUSEABLE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
set(PAUSEABLE_JSON_INCLUDE "${PAUSEABLE_ROOT}/Pauseable.third_party")
if(NOT EXISTS "${PAUSEABLE_JSON_INCLUDE}/nlohmann/json.hpp")
    message(FATAL_ERROR "Missing pinned nlohmann JSON header: apply the complete C-stage bundle")
endif()
add_library(pauseable_mmwave STATIC
    ../integration/src/MmWaveContract.cpp
    ../integration/src/MmWaveTracker.cpp
    ../integration/src/MmWaveReceiver.cpp
    ../integration/src/MmWaveArchive.cpp
)
target_compile_features(pauseable_mmwave PUBLIC cxx_std_17)
target_include_directories(pauseable_mmwave PUBLIC
    "${CMAKE_CURRENT_LIST_DIR}/../integration/include"
    "${PAUSEABLE_JSON_INCLUDE}"
)
target_link_libraries(pauseable_mmwave PUBLIC Threads::Threads)
if(WIN32)
    target_link_libraries(pauseable_mmwave PUBLIC ws2_32)
endif()
