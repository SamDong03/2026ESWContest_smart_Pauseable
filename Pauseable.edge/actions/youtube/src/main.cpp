#include <iostream>
#include <thread>
#include <csignal>
#include <chrono>
#include <sdbus-c++/sdbus-c++.h>
#include <alog.hpp>
#include <amclient/AMClient.h>


#define USE_SD_EVENT

#ifdef USE_SD_EVENT
#include <systemd/sd-event.h>
#endif

#include "example.h"

#define APP_ID "com.atlas.app.pauseableyoutubebridge"


volatile sig_atomic_t g_stop_requested = 0;
void signalHandler(int signal) {
    alog::logInfo("APP_SIGNAL_RECEIVED", "Received signal: {}", signal);
    g_stop_requested = 1;
}

int main()
{
    alog::logInfo("TEST", "map test -> {}", sdbus::ServiceName("org.freedesktop.DBus"));
    try {


        std::shared_ptr<sdbus::IConnection> connection = sdbus::createSystemBusConnection();


        AMClient client(APP_ID);

        client.registerRestartEventCallback([](const std::vector<std::string>& params) {
            try {
                alog::logInfo("EVT_RESTART", "Restart event callback executing with params:");
                for (size_t i = 0; i < params.size(); i++) {
                    alog::logInfo("EVT_RESTART", "  arg[{}]: {}", i, params[i]);
                }
                alog::logInfo("EVT_RESTART", "Restart event handling completed");
            } catch (const std::exception& e) {
                alog::logError("EVT_RESTART", "Exception in restart callback: {}", e.what());
            }
        });

        client.registerPauseEventCallback([](const std::vector<std::string>& params) {
            try {
                alog::logInfo("EVT_PAUSE", "Pause event callback executing with params:");
                for (size_t i = 0; i < params.size(); i++) {
                    alog::logInfo("EVT_PAUSE", "  arg[{}]: {}", i, params[i]);
                }
                alog::logInfo("EVT_PAUSE", "Pause event handling completed");
            } catch (const std::exception& e) {
                alog::logError("EVT_PAUSE", "Exception in pause callback: {}", e.what());
            }
        });

        alog::logInfo("EVT_REGISTERED", "Event callbacks registered");
        client.initializeCallbacks();

        alog::logInfo("TEST", "\033[32mThe app is launched successfully.....\033[0m", sdbus::ServiceName("org.freedesktop.DBus"));

#ifndef USE_SD_EVENT


        usePropertyManagerWithObserver(connection);


        std::signal(SIGINT, signalHandler);
        std::signal(SIGTERM, signalHandler);

        connection->enterEventLoopAsync();


        while (!g_stop_requested) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }

        connection->leaveEventLoop();
#else

        __attribute__((cleanup(sd_event_unrefp))) sd_event *event = NULL;
        __attribute__((cleanup(sd_event_source_unrefp))) sd_event_source *timer = NULL;


        sd_event_default(&event);


        sd_event_add_time_relative(event, &timer, CLOCK_MONOTONIC, 1000000, 0, [] (sd_event_source *s, uint64_t usec, void *userdata) {
            alog::logInfo("TIMER_EXPIRED", "Timer expired after 1 seconds");
            return 0;
        }, NULL);


        usePropertyManagerWithObserver(connection);


        auto manual_proxy = sdbus::createProxy(
            *connection,
            sdbus::ServiceName("org.freedesktop.DBus"),
            sdbus::ObjectPath("/org/freedesktop/DBus")
        );
        std::string well_known_name = "com.atlas.PropertyManager1";
        std::string response;
        try {
            manual_proxy->callMethod("GetNameOwner")
                .onInterface("org.freedesktop.DBus")
                .withArguments(well_known_name)
                .storeResultsTo(response);
            alog::logInfo("DBUS_GETNAMEOWNER", "GetNameOwner response: '{} = '{}'", well_known_name, response);
        } catch (const std::exception& e) {
            alog::logError("DBUS_GETNAMEOWNER", "Failed to call GetNameOwner: {}", e.what());
        }


        connection->attachSdEventLoop(event);


        struct sigaction sa = {};
        sa.sa_handler = signalHandler;
        sa.sa_flags = 0;
        sigemptyset(&sa.sa_mask);

        if (sigaction(SIGINT, &sa, nullptr) < 0 || sigaction(SIGTERM, &sa, nullptr) < 0) {
            alog::logWarn("SIGNAL_SETUP", "Failed to set up signal handlers. Signals may not be handled correctly.");
        }


        while (!g_stop_requested) {
            int r = sd_event_run(event, 100000);
            if (r < 0 && r != -EINTR) {
                alog::logError("APP_EVENTLOOP", "Failed to run event loop: {}", strerror(-r));
                return 1;
            }
        }
#endif
    }
    catch (const std::exception& e) {
        alog::logError("APP_EXCEPTION", "Exception: {}", e.what());
        return 1;
    }

    alog::logInfo("APP_EXIT", "Application stopped. Exiting...");
    return 0;
}
