#ifndef PIPER_H_
#define PIPER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <uchar.h>

#if defined (WIN32) && (defined(__GNUC__) || defined (_MSC_VER))
#if defined(BUILDING_LIBPIPER)
#define EXPORT_SYMBOL __declspec( dllexport )
#else
#define EXPORT_SYMBOL __declspec( dllimport )
#endif
#else
#define EXPORT_SYMBOL
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define PIPER_OK 0
#define PIPER_DONE 1
#define PIPER_ERR_GENERIC -1


typedef struct piper_synthesizer piper_synthesizer;


typedef struct piper_audio_chunk {


  const float *samples;


  size_t num_samples;


  int sample_rate;


  bool is_last;


  const char32_t *phonemes;


  size_t num_phonemes;


  const int *phoneme_ids;


  size_t num_phoneme_ids;


  const int *alignments;


  size_t num_alignments;
} piper_audio_chunk;


typedef struct piper_synthesize_options {


  int speaker_id;


  float length_scale;


  float noise_scale;


  float noise_w_scale;
} piper_synthesize_options;


EXPORT_SYMBOL
piper_synthesizer *piper_create(const char *model_path, const char *config_path,
                                const char *espeak_data_path);


EXPORT_SYMBOL
void piper_free(piper_synthesizer *synth);


EXPORT_SYMBOL
piper_synthesize_options
piper_default_synthesize_options(piper_synthesizer *synth);


EXPORT_SYMBOL
int piper_synthesize_start(piper_synthesizer *synth, const char *text,
                           const piper_synthesize_options *options);


EXPORT_SYMBOL
int piper_synthesize_next(piper_synthesizer *synth, piper_audio_chunk *chunk);


EXPORT_SYMBOL
char const *piper_version(void);


#ifdef __cplusplus
}
#endif

#endif
