#ifndef ULID_CORE_H
#define ULID_CORE_H

#include <array>
#include <chrono>
#include <cstdint>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#include <Windows.h>
#include <bcrypt.h>
#pragma comment(lib, "bcrypt.lib")
#else
#include <sys/random.h>
#endif

namespace ulid_core {
using Bytes = std::array<std::uint8_t, 16>;
constexpr std::uint64_t max_timestamp = (std::uint64_t{1} << 48) - 1;
constexpr char alphabet[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

inline int digit(unsigned char c) {
    if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    for (int i = 0; i < 32; ++i) if (c == alphabet[i]) return i;
    return -1;
}

inline Bytes decode(const std::string& text) {
    if (text.size() != 26) throw std::invalid_argument("ULID must contain exactly 26 ASCII characters");
    Bytes bytes{};
    for (int i = 0; i < 26; ++i) {
        const int value = digit(static_cast<unsigned char>(text[i]));
        if (value < 0 || (i == 0 && value > 7))
            throw std::invalid_argument("Invalid ULID alphabet or 128-bit overflow");
        for (int j = 0; j < 5; ++j) {
            const int bit = i * 5 + j - 2;
            if (bit >= 0) bytes[bit / 8] |= ((value >> (4 - j)) & 1) << (7 - bit % 8);
        }
    }
    return bytes;
}

inline std::string encode(const Bytes& bytes) {
    std::string text(26, '0');
    for (int i = 0; i < 26; ++i) {
        int value = 0;
        for (int j = 0; j < 5; ++j) {
            const int bit = i * 5 + j - 2;
            value = (value << 1) | (bit < 0 ? 0 : (bytes[bit / 8] >> (7 - bit % 8)) & 1);
        }
        text[i] = alphabet[value];
    }
    return text;
}

inline std::uint64_t timestamp(const Bytes& bytes) {
    std::uint64_t value = 0;
    for (int i = 0; i < 6; ++i) value = (value << 8) | bytes[i];
    return value;
}

inline void secure_entropy(std::uint8_t* output, std::size_t size) {
#ifdef _WIN32
    if (BCryptGenRandom(nullptr, output, static_cast<ULONG>(size),
                        BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
#else
    if (getentropy(output, size) != 0)
#endif
        throw std::runtime_error("OS secure random generator failed");
}

inline std::uint64_t clock_ms() {
    const auto value = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    if (value < 0) throw std::runtime_error("System clock precedes Unix epoch");
    return static_cast<std::uint64_t>(value);
}

class Generator {
public:
    using Clock = std::function<std::uint64_t()>;
    using Entropy = std::function<void(std::uint8_t*, std::size_t)>;

    Bytes next(const Clock& clock = clock_ms, const Entropy& entropy = secure_entropy) {
        std::lock_guard<std::mutex> guard(mutex_);
        const auto now = clock();
        if (now > max_timestamp) throw std::overflow_error("Timestamp exceeds 48 bits");
        Bytes candidate = last_;
        if (!initialized_ || now > timestamp(last_)) {
            auto remaining = now;
            for (int i = 5; i >= 0; --i) {
                candidate[i] = static_cast<std::uint8_t>(remaining);
                remaining >>= 8;
            }
            entropy(candidate.data() + 6, 10);
        } else {
            int i = 15;
            while (i >= 6 && ++candidate[i] == 0) --i;
            if (i < 6) throw std::overflow_error("Monotonic ULID entropy exhausted");
        }
        last_ = candidate;
        initialized_ = true;
        return candidate;
    }

private:
    std::mutex mutex_;
    bool initialized_ = false;
    Bytes last_{};
};
}
#endif
