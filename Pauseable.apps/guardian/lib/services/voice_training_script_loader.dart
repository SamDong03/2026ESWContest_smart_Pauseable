import 'dart:convert';

import 'package:flutter/services.dart';

import '../models/voice_training_prompt.dart';

class VoiceTrainingScriptLoader {
  static VoiceTrainingScript? _cached;

  static Future<VoiceTrainingScript> load() async {
    final cached = _cached;
    if (cached != null) return cached;
    final source = await rootBundle.loadString(
      'assets/data/voice_training_script.json',
    );
    return _cached = VoiceTrainingScript.fromJson(
      jsonDecode(source) as Map<String, dynamic>,
    );
  }
}
