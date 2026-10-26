
cmake_minimum_required(VERSION 3.14)
project(com.atlas.app.pauseableatlas)

include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(sdbus-c++ 2.0 REQUIRED)
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)

add_subdirectory(mmwave)


file(READ ${CMAKE_CURRENT_SOURCE_DIR}/config/ha_config.json HA_CONFIG_JSON)
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/generated)
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/config/EmbeddedHaConfig.hpp.in
    ${CMAKE_CURRENT_BINARY_DIR}/generated/EmbeddedHaConfig.hpp
    @ONLY
)


add_library(pauseable_core STATIC
    core/src/ActionRouter.cpp
    core/src/BehaviorInference.cpp
    core/src/DecisionEvent.cpp
    core/src/DecisionEngine.cpp
)

target_include_directories(pauseable_core
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/core/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../../Pauseable.third_party
        /usr/local/include
)


set(SOURCES
    atlas/src/PropertyManagerClient.cpp
    integration/src/DecisionGatewayClient.cpp
    integration/src/DecisionOutbox.cpp
    integration/src/GatewayClient.cpp
    integration/src/HAEntityClient.cpp
    integration/src/MqttDecisionSubscriber.cpp
    integration/src/PiperTtsEngine.cpp
    src/main.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES})

target_compile_definitions(${PROJECT_NAME}
    PRIVATE
        BOOST_ERROR_CODE_HEADER_ONLY
        BOOST_SYSTEM_NO_LIB
)

target_include_directories(${PROJECT_NAME}
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../../Pauseable.third_party
        ${CMAKE_CURRENT_SOURCE_DIR}/atlas/include
        ${CMAKE_CURRENT_SOURCE_DIR}/integration/include
        ${CMAKE_CURRENT_SOURCE_DIR}/core/include
        ${CMAKE_CURRENT_BINARY_DIR}/generated
        /usr/local/include
)

target_link_libraries(${PROJECT_NAME}
    PRIVATE
        pauseable_core
        pauseable_mmwave
        Threads::Threads
        OpenSSL::SSL
        OpenSSL::Crypto
        SDBusCpp::sdbus-c++
        property-manager-core
        systemd
        amclient
        alog
        fmt
)

set(APP_INSTALL_DIR ${CMAKE_INSTALL_PREFIX}/apps/${PROJECT_NAME})

install(
    TARGETS ${PROJECT_NAME}
    DESTINATION ${APP_INSTALL_DIR}
)

install(
    FILES ${CMAKE_CURRENT_SOURCE_DIR}/files/appinfo.json
    DESTINATION ${APP_INSTALL_DIR}
)

option(PAUSEABLE_BUILD_TESTS "Build Pauseable Central host-independent tests" OFF)
if(PAUSEABLE_BUILD_TESTS)
    enable_testing()
    add_executable(behavior_inference_test tests/behavior_inference_test.cpp)
    target_include_directories(behavior_inference_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../../Pauseable.third_party
    )
    target_link_libraries(behavior_inference_test PRIVATE pauseable_core)
    add_test(NAME behavior_inference_test COMMAND behavior_inference_test)

    add_executable(action_router_test tests/action_router_test.cpp)
    target_include_directories(action_router_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../../Pauseable.third_party
    )
    target_link_libraries(action_router_test PRIVATE pauseable_core)
    add_test(NAME action_router_test COMMAND action_router_test)

    add_executable(decision_outbox_test
        tests/decision_outbox_test.cpp
        integration/src/DecisionOutbox.cpp
    )
    target_include_directories(decision_outbox_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/integration/include
        ${CMAKE_CURRENT_SOURCE_DIR}/../../Pauseable.third_party
    )
    target_link_libraries(decision_outbox_test PRIVATE Threads::Threads)
    add_test(NAME decision_outbox_test COMMAND decision_outbox_test)
endif()
