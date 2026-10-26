cmake_minimum_required(VERSION 3.14)
project(com.atlas.app.pauseableyoutubebridge)


include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


find_package(sdbus-c++ 2.0 REQUIRED)


set(SOURCES
    src/example.cpp
    src/main.cpp
)


add_executable(${PROJECT_NAME} ${SOURCES})


target_include_directories(${PROJECT_NAME}
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        /usr/local/include
)


target_link_libraries(${PROJECT_NAME}
    PRIVATE
        SDBusCpp::sdbus-c++
        property-manager-core
        systemd
        amclient
        alog
        fmt
)


set(APP_INSTALL_DIR ${CMAKE_INSTALL_PREFIX}/apps/${PROJECT_NAME})
install(TARGETS ${PROJECT_NAME} DESTINATION ${APP_INSTALL_DIR})
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/files/appinfo.json DESTINATION ${APP_INSTALL_DIR})
