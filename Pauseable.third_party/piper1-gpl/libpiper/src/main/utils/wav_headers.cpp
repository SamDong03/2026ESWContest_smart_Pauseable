#include "wav_headers.hpp"

namespace
{
    template <typename T>
    void writeNumber(T num, std::ostream &stream)
    {
        stream.write(reinterpret_cast<char *>(&num), sizeof(num));
    }
}

void writeWavStreamHeader(std::ostream &stream, int sample_rate)
{
    const std::size_t unspec_count = 0x7ffff000;


    stream.write("RIFF", 4);

    writeNumber<uint32_t>(unspec_count + 36, stream);

    stream.write("WAVE", 4);


    stream.write("fmt ", 4);

    writeNumber<uint32_t>(16, stream);

    writeNumber<uint16_t>(3, stream);

    writeNumber<uint16_t>(1, stream);

    writeNumber<uint32_t>(sample_rate, stream);

    writeNumber<uint32_t>(sample_rate * 4, stream);

    writeNumber<uint16_t>(4, stream);

    writeNumber<uint16_t>(32, stream);


    stream.write("data", 4);

    writeNumber<uint32_t>(unspec_count, stream);
}
