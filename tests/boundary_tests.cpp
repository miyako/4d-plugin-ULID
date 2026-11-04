#include "4DPluginAPI.h"
#include "ulid_core.h"
#include <cstring>
#include <iostream>
#include <vector>

namespace {
using Text = std::basic_string<PA_Unichar>;
struct Host {
    PluginBlock block{};
    PA_Unistring parameters[2]{};
    Text inputs[2];
    Text result;
    std::vector<std::uint8_t> blob;
    double real = 0;
    PA_long32 integer = 0;
    int returns = 0;
    int copies = 0;

    Host() { block.fData = reinterpret_cast<void**>(this); }
    void input(int index, const std::string& text) {
        inputs[index].assign(text.begin(), text.end());
        parameters[index].fString = const_cast<PA_Unichar*>(inputs[index].c_str());
        parameters[index].fLength = static_cast<PA_long32>(text.size());
    }
    bool error() const { return parameters[1].fLength != 0; }
};
Host& host(PA_PluginParameters params) { return *reinterpret_cast<Host*>(params->fData); }
void check(bool condition) { if (!condition) throw std::runtime_error("Boundary assertion failed"); }
std::string ascii(const Text& text) { return {text.begin(), text.end()}; }
}

extern "C" {
PA_Unistring* PA_GetStringParameter(PA_PluginParameters params, short index) {
    return &host(params).parameters[index - 1];
}
void PA_SetUnistring(PA_Unistring* output, PA_Unichar* text) {
    std::size_t length = 0;
    while (text[length]) ++length;
    // This mock stores only the error length, which is all its assertions use.
    output->fLength = static_cast<PA_long32>(length);
}
void PA_ReturnString(PA_PluginParameters params, PA_Unichar* text) {
    host(params).result = text;
    ++host(params).returns;
}
void PA_ReturnBlob(PA_PluginParameters params, void* bytes, PA_long32 size) {
    auto* begin = static_cast<std::uint8_t*>(bytes);
    host(params).blob.assign(begin, begin + size);
    ++host(params).returns;
}
PA_long32 PA_GetBlobParameter(PA_PluginParameters params, short, void* bytes) {
    auto& h = host(params);
    if (bytes) {
        ++h.copies;
        std::memcpy(bytes, h.blob.data(), h.blob.size());
    }
    return static_cast<PA_long32>(h.blob.size());
}
void PA_ReturnDouble(PA_PluginParameters params, double value) {
    host(params).real = value;
    ++host(params).returns;
}
void PA_ReturnLong(PA_PluginParameters params, PA_long32 value) {
    host(params).integer = value;
    ++host(params).returns;
}
}

int main() {
    try {
        const std::string canonical = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
        Host to;
        to.input(0, canonical);
        PluginMain(7, &to.block);
        const auto expected = ulid_core::decode(canonical);
        check(!to.error() && to.returns == 1 && to.blob.size() == 16);
        check(std::equal(to.blob.begin(), to.blob.end(), expected.begin()));
        Host from;
        from.blob = to.blob;
        PluginMain(8, &from.block);
        check(!from.error() && from.returns == 1 && ascii(from.result) == canonical);
        for (auto size : {0, 15, 17, 100000}) {
            Host bad;
            bad.blob.resize(size);
            PluginMain(8, &bad.block);
            check(bad.error() && bad.returns == 1 && bad.copies == 0 && bad.result.empty());
        }
        Host invalid;
        invalid.input(0, "80000000000000000000000000");
        PluginMain(7, &invalid.block);
        check(invalid.error() && invalid.blob.empty() && invalid.returns == 1);
        invalid.input(0, std::string(100000, '0'));
        PluginMain(7, &invalid.block);
        check(invalid.error() && invalid.blob.empty());
        invalid.input(0, canonical);
        invalid.inputs[0][0] = 0x100;
        PluginMain(7, &invalid.block);
        check(invalid.error() && invalid.blob.empty());
        Host stamp;
        stamp.input(0, "7ZZZZZZZZZZZZZZZZZZZZZZZZZ");
        PluginMain(9, &stamp.block);
        check(!stamp.error() && stamp.real == static_cast<double>(ulid_core::max_timestamp));
        stamp.input(0, "bad");
        PluginMain(9, &stamp.block);
        check(stamp.error() && stamp.real == -1);
        stamp.input(0, canonical);
        PluginMain(9, &stamp.block);
        check(!stamp.error() && stamp.real == 1469922850259ULL);
        Host validation;
        validation.input(0, "01arz3ndektsv4rrffq69g5fav");
        PluginMain(10, &validation.block);
        check(validation.integer == 1);
        validation.input(0, "bad");
        PluginMain(10, &validation.block);
        check(validation.integer == 0);
        Host generation;
        PluginMain(6, &generation.block);
        check(generation.parameters[0].fLength == 0 && generation.result.size() == 26);
        const auto first = generation.result;
        PluginMain(6, &generation.block);
        check(first < generation.result);
        Host obsolete_generation;
        obsolete_generation.input(0, "");
        PluginMain(3, &obsolete_generation.block);
        check(obsolete_generation.returns == 1 && obsolete_generation.result.size() == 26);
        check(ulid_core::encode(ulid_core::decode(ascii(obsolete_generation.result))) ==
              ascii(obsolete_generation.result));
        obsolete_generation.input(0, "still ignored");
        PluginMain(3, &obsolete_generation.block);
        check(obsolete_generation.returns == 2 && obsolete_generation.result.size() == 26);
        Host legacy;
        legacy.input(0, "0000587cea2c04040404040404040404");
        PluginMain(1, &legacy.block);
        check(ascii(legacy.result) == "0001C7STHC0G2081040G208104");
        legacy.input(0, ascii(legacy.result));
        PluginMain(2, &legacy.block);
        check(ascii(legacy.result) == "0000587cea2c04040404040404040404");
        std::cout << "Mock SDK boundary tests passed (not a 4D runtime test)\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
