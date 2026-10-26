#pragma once

#include "PropertyManager1Proxy.h"

class PropertyManagerProxy : public com::atlas::PropertyManager1_proxy
{
public:
    PropertyManagerProxy(sdbus::IProxy& proxy);
    ~PropertyManagerProxy() = default;
    void onPropertyChanged(const std::string& id, const sdbus::Variant& value);

private:
    sdbus::IProxy& proxy_;
};

void usePropertyManagerWithObserver(std::shared_ptr<sdbus::IConnection> connection);
