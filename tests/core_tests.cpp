#include "ulid_core.h"
#include <algorithm>
#include <iostream>
#include <set>
#include <thread>
#include <vector>

static void check(bool condition) {
    if (!condition) throw std::runtime_error("Test assertion failed");
}
template<class Function> static void rejects(Function function) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    check(rejected);
}

int main() {
    using namespace ulid_core;
    try {
        const std::string canonical = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
        const Bytes expected{{0x01,0x56,0x3e,0x3a,0xb5,0xd3,0xd6,0x76,
                              0x4c,0x61,0xef,0xb9,0x93,0x02,0xbd,0x5b}};
        check(decode(canonical) == expected);
        check(encode(expected) == canonical);
        check(timestamp(expected) == 1469922850259ULL);
        check(encode(decode("01arz3ndektsv4rrffq69g5fav")) == canonical);
        check(timestamp(decode("7ZZZZZZZZZZZZZZZZZZZZZZZZZ")) == max_timestamp);
        check(encode(Bytes{}) == std::string(26, '0'));
        for (const auto& text : {"", "0", "80000000000000000000000000",
                                "01ARZ3NDEKTSV4RRFFQ69G5FAI", "01ARZ3NDEKTSV4RRFFQ69G5FAL",
                                "01ARZ3NDEKTSV4RRFFQ69G5FAO", "01ARZ3NDEKTSV4RRFFQ69G5FAU"})
            rejects([&] { decode(text); });
        rejects([&] { decode(std::string(26, '\xff')); });
        rejects([&] { decode(std::string(26, '\0')); });
        for (int sample = 0; sample < 256; ++sample) {
            Bytes value{};
            for (std::size_t i = 0; i < value.size(); ++i)
                value[i] = static_cast<std::uint8_t>(sample + i);
            check(decode(encode(value)) == value);
        }

        Generator generator;
        std::uint64_t now = 42;
        int calls = 0;
        auto clock = [&] { return now; };
        auto entropy = [&](std::uint8_t* output, std::size_t size) {
            ++calls;
            std::fill(output, output + size, 0);
        };
        const auto first = generator.next(clock, entropy);
        const auto second = generator.next(clock, entropy);
        check(first < second && calls == 1 && timestamp(first) == 42);
        now = 1;
        check(second < generator.next(clock, entropy) && calls == 1);
        now = 43;
        rejects([&] {
            generator.next(clock, [](std::uint8_t* output, std::size_t) {
                output[0] = 123;
                throw std::runtime_error("Injected RNG failure");
            });
        });
        now = 42;
        auto after_failure = generator.next(clock, entropy);
        check(timestamp(after_failure) == 42 && after_failure[15] == 3);
        now = max_timestamp + 1;
        rejects([&] { generator.next(clock, entropy); });
        Generator fresh;
        rejects([&] {
            fresh.next([] { return 7; }, [](std::uint8_t*, std::size_t) {
                throw std::runtime_error("Initial entropy failure");
            });
        });
        check(timestamp(fresh.next([] { return 6; }, entropy)) == 6);

        Generator exhausted;
        auto maximum = [](std::uint8_t* output, std::size_t size) {
            std::fill(output, output + size, 255);
        };
        now = 42;
        auto last = exhausted.next(clock, maximum);
        rejects([&] { exhausted.next(clock, entropy); });
        rejects([&] { exhausted.next(clock, entropy); });
        now = 43;
        check(exhausted.next(clock, entropy) > last);

        Generator concurrent;
        std::mutex results_mutex;
        std::vector<std::string> results;
        std::vector<std::thread> threads;
        for (int i = 0; i < 8; ++i) threads.emplace_back([&] {
            for (int j = 0; j < 1000; ++j) {
                auto text = encode(concurrent.next([] { return 100; },
                    [](std::uint8_t* output, std::size_t size) {
                        std::fill(output, output + size, 0);
                    }));
                std::lock_guard<std::mutex> guard(results_mutex);
                results.push_back(text);
            }
        });
        for (auto& thread : threads) thread.join();
        check(std::set<std::string>(results.begin(), results.end()).size() == 8000);
        std::sort(results.begin(), results.end());
        for (int i = 0; i < 8000; ++i) {
            const auto value = decode(results[i]);
            check(timestamp(value) == 100);
            check(value[14] == i / 256 && value[15] == i % 256);
        }
        check(timestamp(generator.next()) <= max_timestamp);
        std::cout << "ULID core tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
