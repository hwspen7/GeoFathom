cmake_minimum_required(VERSION 3.20)
project(GeoFathomNative LANGUAGES CXX)

include(CTest)

add_library(geofathom_native SHARED geometry/native/geometry.cpp geometry/native/mask.cpp geometry/native/editor.cpp)
target_compile_features(geofathom_native PUBLIC cxx_std_17)
target_include_directories(geofathom_native PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/geometry/native)
set_target_properties(geofathom_native PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
)

if(BUILD_TESTING)
  add_executable(geofathom_native_tests geometry/native/test_geometry.cpp)
  target_link_libraries(geofathom_native_tests PRIVATE geofathom_native)
  target_compile_features(geofathom_native_tests PRIVATE cxx_std_17)
  add_test(NAME geometry_kernels COMMAND geofathom_native_tests)
endif()
