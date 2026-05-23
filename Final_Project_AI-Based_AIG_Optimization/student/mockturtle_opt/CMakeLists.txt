cmake_minimum_required(VERSION 3.16)
project(student_mockturtle_opt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})

set(MOCKTURTLE_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../mockturtle_src")

add_executable(mockturtle_opt mockturtle_opt.cpp)
target_compile_definitions(mockturtle_opt PRIVATE FMT_HEADER_ONLY)
target_compile_options(mockturtle_opt PRIVATE -O2 -DNDEBUG)
target_include_directories(mockturtle_opt PRIVATE
  "${MOCKTURTLE_SRC}/include"
  "${MOCKTURTLE_SRC}/lib/kitty"
  "${MOCKTURTLE_SRC}/lib/lorina"
  "${MOCKTURTLE_SRC}/lib/parallel_hashmap"
  "${MOCKTURTLE_SRC}/lib/fmt"
  "${MOCKTURTLE_SRC}/lib/percy"
  "${MOCKTURTLE_SRC}/lib/bill"
  "${MOCKTURTLE_SRC}/lib/rang"
  "${MOCKTURTLE_SRC}/lib/nauty"
  "${MOCKTURTLE_SRC}/lib/abcsat"
  "${MOCKTURTLE_SRC}/lib/abcesop"
)
