export 'native_push_platform_interface.dart';

import 'native_push_platform_stub.dart'
    if (dart.library.io) 'native_push_platform_android.dart'
    as implementation;
import 'native_push_platform_interface.dart';

NativePushPlatform createNativePushPlatform() =>
    implementation.createNativePushPlatform();
