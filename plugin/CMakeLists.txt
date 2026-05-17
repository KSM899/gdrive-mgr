cmake_minimum_required(VERSION 3.16)
project(gdrive-mgr-overlay LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Default to /usr so the plugin installs to the same Qt plugin search path
# Dolphin uses out of the box. Install with `sudo cmake --install build`.
# (User-local plugin discovery in KF6 requires setting QT_PLUGIN_PATH for
# every Qt app you want it loaded into — not worth it for one plugin.)
if(NOT CMAKE_INSTALL_PREFIX OR CMAKE_INSTALL_PREFIX STREQUAL "/usr/local")
    set(CMAKE_INSTALL_PREFIX "/usr" CACHE PATH "" FORCE)
endif()

find_package(ECM 5.240 NO_MODULE REQUIRED)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui)
find_package(KF6 REQUIRED COMPONENTS KIO)

kcoreaddons_add_plugin(gdrivemgroverlay
    SOURCES GDriveOverlayPlugin.cpp
    INSTALL_NAMESPACE "kf6/overlayicon"
)

target_link_libraries(gdrivemgroverlay KF6::KIOCore Qt6::Gui)
