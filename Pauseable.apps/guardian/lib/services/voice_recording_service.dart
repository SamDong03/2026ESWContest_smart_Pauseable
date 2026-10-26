import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

typedef VoiceRecorderFactory = VoiceRecordingService Function();

VoiceRecordingService createDeviceVoiceRecorder() =>
    DeviceVoiceRecordingService();

class VoiceRecording {
  const VoiceRecording({
    required this.bytes,
    required this.duration,
    required this.fileName,
  });

  final Uint8List bytes;
  final Duration duration;
  final String fileName;
}

abstract interface class VoiceRecordingService {
  Future<bool> start();

  Future<VoiceRecording> stop();

  Future<void> cancel();

  Future<void> dispose();
}

class DeviceVoiceRecordingService implements VoiceRecordingService {
  static const _sampleRate = 16000;
  static const _channelCount = 1;
  static const _bitsPerSample = 16;

  final AudioRecorder _recorder = AudioRecorder();
  BytesBuilder _pcmBuffer = BytesBuilder(copy: false);
  StreamSubscription<Uint8List>? _streamSubscription;
  Completer<void>? _streamDone;
  Stopwatch? _stopwatch;
  Object? _streamError;
  bool _isRecording = false;

  @override
  Future<bool> start() async {
    if (_isRecording) return true;
    if (!await _recorder.hasPermission()) return false;

    _pcmBuffer = BytesBuilder(copy: false);
    _streamError = null;
    _streamDone = Completer<void>();
    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _sampleRate,
        numChannels: _channelCount,
        autoGain: true,
        echoCancel: true,
        noiseSuppress: true,
      ),
    );
    _streamSubscription = stream.listen(
      _pcmBuffer.add,
      onError: (Object error) {
        _streamError = error;
        if (!(_streamDone?.isCompleted ?? true)) _streamDone!.complete();
      },
      onDone: () {
        if (!(_streamDone?.isCompleted ?? true)) _streamDone!.complete();
      },
      cancelOnError: true,
    );
    _stopwatch = Stopwatch()..start();
    _isRecording = true;
    return true;
  }

  @override
  Future<VoiceRecording> stop() async {
    if (!_isRecording) {
      throw StateError('진행 중인 음성 녹음이 없습니다.');
    }

    _stopwatch?.stop();
    await _recorder.stop();
    await _streamDone?.future.timeout(
      const Duration(seconds: 1),
      onTimeout: () {},
    );
    await _streamSubscription?.cancel();
    _streamSubscription = null;
    _isRecording = false;

    final streamError = _streamError;
    if (streamError != null) {
      throw StateError('녹음 데이터를 읽지 못했습니다: $streamError');
    }

    final pcmBytes = _pcmBuffer.takeBytes();
    if (pcmBytes.isEmpty) {
      throw StateError('녹음된 음성이 없습니다. 잠시 말한 뒤 다시 시도해 주세요.');
    }

    final timestamp = DateTime.now().toIso8601String().replaceAll(
      RegExp(r'[^0-9]'),
      '',
    );
    return VoiceRecording(
      bytes: _createWaveFile(pcmBytes),
      duration: _stopwatch?.elapsed ?? Duration.zero,
      fileName: 'guardian-voice-$timestamp.wav',
    );
  }

  @override
  Future<void> cancel() async {
    if (_isRecording) await _recorder.cancel();
    await _streamSubscription?.cancel();
    _streamSubscription = null;
    _isRecording = false;
    _stopwatch?.stop();
    _pcmBuffer = BytesBuilder(copy: false);
  }

  @override
  Future<void> dispose() async {
    await cancel();
    await _recorder.dispose();
  }

  Uint8List _createWaveFile(Uint8List pcmBytes) {
    const headerLength = 44;
    const byteRate = _sampleRate * _channelCount * _bitsPerSample ~/ 8;
    const blockAlign = _channelCount * _bitsPerSample ~/ 8;
    final wave = Uint8List(headerLength + pcmBytes.length);
    final header = ByteData.sublistView(wave, 0, headerLength);

    _writeAscii(wave, 0, 'RIFF');
    header.setUint32(4, 36 + pcmBytes.length, Endian.little);
    _writeAscii(wave, 8, 'WAVE');
    _writeAscii(wave, 12, 'fmt ');
    header.setUint32(16, 16, Endian.little);
    header.setUint16(20, 1, Endian.little);
    header.setUint16(22, _channelCount, Endian.little);
    header.setUint32(24, _sampleRate, Endian.little);
    header.setUint32(28, byteRate, Endian.little);
    header.setUint16(32, blockAlign, Endian.little);
    header.setUint16(34, _bitsPerSample, Endian.little);
    _writeAscii(wave, 36, 'data');
    header.setUint32(40, pcmBytes.length, Endian.little);
    wave.setRange(headerLength, wave.length, pcmBytes);
    return wave;
  }

  void _writeAscii(Uint8List target, int offset, String value) {
    for (var index = 0; index < value.length; index++) {
      target[offset + index] = value.codeUnitAt(index);
    }
  }
}
