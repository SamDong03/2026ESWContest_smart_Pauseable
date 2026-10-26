#pragma once


#include "PropertyManager1Proxy.h"

#include <memory>

class PropertyManagerProxy : public com::atlas::PropertyManager1_proxy
{
public:
    explicit PropertyManagerProxy(sdbus::IProxy& proxy);
    ~PropertyManagerProxy() = default;
    void onPropertyChanged(const std::string& id, const sdbus::Variant& value) override;

private:
    sdbus::IProxy& proxy_;
};

void usePropertyManagerWithObserver(std::shared_ptr<sdbus::IConnection> connection);
