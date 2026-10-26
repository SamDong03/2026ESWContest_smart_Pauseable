#pragma once


#include <sdbus-c++/sdbus-c++.h>
#include <memory>
#include <functional>
#include <alog.hpp>

template<typename T>
class DBusObserver {
public:
    DBusObserver(std::shared_ptr<sdbus::IConnection> connection,
                 const std::string& serviceName,
                 const std::string& objectPath,
                 std::function<void(T*)> cb_connect,
                 std::function<void(T*)> cb_disconnect = nullptr)
        : m_connection(connection)
        , m_connectCB(cb_connect)
        , m_disconnCB(cb_disconnect)
        , m_serviceName(serviceName)
        , m_objectPath(objectPath)
    {
        m_proxy = sdbus::createProxy(
            *m_connection,
            sdbus::ServiceName("org.freedesktop.DBus"),
            sdbus::ObjectPath("/org/freedesktop/DBus")
        );

        std::string owner;
        try {
            m_proxy->callMethod("GetNameOwner").onInterface("org.freedesktop.DBus").withArguments(serviceName).storeResultsTo(owner);
            alog::logInfo("DBUS_OBSERVER", "[Observer:{}] Service Exist - {}", m_connection->getUniqueName(), serviceName);
            tryConnect();
        } catch (const sdbus::Error&) {
            alog::logInfo("DBUS_OBSERVER", "[Observer:{}] Service not exist - {} waiting for it", m_connection->getUniqueName(), serviceName);
        }

        m_proxy->uponSignal("NameOwnerChanged").onInterface("org.freedesktop.DBus").call(
            [this](const std::string& name, const std::string& oldOwner, const std::string& newOwner) {
                (void)oldOwner;
                auto uniqName = m_connection->getUniqueName();
                if (name == m_serviceName) {
                    if (!newOwner.empty()) {
                        alog::logInfo("DBUS_OBSERVER", "[Observer:{}] Service UP - {}", uniqName, m_serviceName);
                        tryConnect();
                    } else {
                        alog::logInfo("DBUS_OBSERVER", "[Observer:{}] Service DOWN - {}", uniqName, m_serviceName);
                        if (m_disconnCB) {
                            m_disconnCB(m_object.get());
                        }
                        m_object.reset();
                        m_clientProxy.reset();
                    }
                }
            });
    }

    void tryConnect() {
        try {
            m_clientProxy = sdbus::createProxy(*m_connection, m_serviceName, m_objectPath);
            m_object = std::make_unique<T>(*m_clientProxy);
            if (m_connectCB) {
                m_connectCB(m_object.get());
            }
        } catch(const sdbus::Error& e) {
            auto uniqName = m_connection->getUniqueName();
            if (e.getName() != "org.freedesktop.DBus.Error.ServiceUnknown") {
                alog::logWarn("DBUS_OBSERVER", "[Observer:{}] connection failed to {} - {}", uniqName, m_serviceName, e.getName());
            } else {
                alog::logDebug("DBUS_OBSERVER", "[Observer:{}] {} is not ready yet: {}", uniqName, m_serviceName, e.what());
            }
        } catch(const std::exception& e) {
            auto uniqName = m_connection->getUniqueName();
            alog::logWarn("DBUS_OBSERVER", "[Observer:{}] unexpected error during connect to {} - {}", uniqName, m_serviceName, e.what());
        }
    }

private:
    std::shared_ptr<sdbus::IConnection> m_connection;
    std::shared_ptr<sdbus::IProxy> m_proxy;

    std::unique_ptr<sdbus::IProxy> m_clientProxy;
    std::unique_ptr<T> m_object;
    sdbus::ServiceName m_serviceName;
    sdbus::ObjectPath m_objectPath;

    std::function<void(T*)> m_connectCB;
    std::function<void(T*)> m_disconnCB;
};
