class VoiceTrainingScript {
  const VoiceTrainingScript({
    required this.version,
    required this.targetSeconds,
    required this.totalPrompts,
    required this.prompts,
  });

  factory VoiceTrainingScript.fromJson(Map<String, dynamic> json) {
    final prompts = (json['prompts'] as List<dynamic>)
        .map(
          (prompt) =>
              VoiceTrainingPrompt.fromJson(prompt as Map<String, dynamic>),
        )
        .toList(growable: false);

    return VoiceTrainingScript(
      version: json['version'] as int,
      targetSeconds: json['target_seconds'] as int,
      totalPrompts: json['total_prompts'] as int,
      prompts: prompts,
    );
  }

  final int version;
  final int targetSeconds;
  final int totalPrompts;
  final List<VoiceTrainingPrompt> prompts;

  VoiceTrainingPrompt? promptForClipCount(int clipCount) {
    if (clipCount < 0) {
      throw ArgumentError.value(clipCount, 'clipCount', 'must not be negative');
    }
    if (clipCount >= prompts.length) return null;
    return prompts[clipCount];
  }
}

class VoiceTrainingPrompt {
  const VoiceTrainingPrompt({
    required this.index,
    required this.id,
    required this.fileName,
    required this.text,
    required this.category,
    required this.tone,
    this.addressee,
  });

  factory VoiceTrainingPrompt.fromJson(Map<String, dynamic> json) {
    return VoiceTrainingPrompt(
      index: json['index'] as int,
      id: json['id'] as String,
      fileName: json['file_name'] as String,
      text: json['text'] as String,
      category: json['category'] as String,
      tone: json['tone'] as String,
      addressee: json['addressee'] as String?,
    );
  }

  final int index;
  final String id;
  final String fileName;
  final String text;
  final String category;
  final String tone;
  final String? addressee;
}
