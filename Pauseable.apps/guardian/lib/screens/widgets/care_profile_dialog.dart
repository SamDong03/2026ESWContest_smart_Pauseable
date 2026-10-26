part of '../guardian_home_page.dart';

class _CareProfileDialog extends StatefulWidget {
  const _CareProfileDialog({required this.repository, this.initial});

  final GuardianRepository repository;
  final GuardianProfile? initial;

  @override
  State<_CareProfileDialog> createState() => _CareProfileDialogState();
}

class _CareProfileDialogState extends State<_CareProfileDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _guardianName;
  late final TextEditingController _patientName;
  late String _relationship;
  late final TextEditingController _patientCallName;
  late final TextEditingController _phone;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _guardianName = TextEditingController(text: widget.initial?.name ?? '');
    _patientName = TextEditingController(
      text: widget.initial?.patientName ?? '',
    );
    _relationship = widget.initial?.relationship ?? '';
    _patientCallName = TextEditingController(
      text: widget.initial?.patientCallName ?? '',
    );
    _phone = TextEditingController(text: widget.initial?.phoneNumber ?? '');
  }

  @override
  void dispose() {
    _guardianName.dispose();
    _patientName.dispose();
    _patientCallName.dispose();
    _phone.dispose();
    super.dispose();
  }

  String? _validateName(String? value) {
    final name = value?.trim() ?? '';
    if (name.isEmpty) return '이름을 입력해 주세요.';
    if (name.length > 40) return '이름은 40자 이내로 입력해 주세요.';
    return null;
  }

  List<String> get _suggestedCallNames => switch (_relationship) {
    '아들' || '딸' => const ['엄마', '아빠', '어머니', '아버지'],
    '손자' || '손녀' => const ['할머니', '할아버지'],
    '배우자' => const ['여보', '당신'],
    _ => const [],
  };

  Future<void> _save() async {
    if (_saving || !_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final saved = await widget.repository.updateGuardianProfile(
        name: _guardianName.text.trim(),
        patientName: _patientName.text.trim(),
        relationship: _relationship,
        patientCallName: _patientCallName.text.trim(),
        phoneNumber: _phone.text.trim(),
      );
      if (mounted) Navigator.of(context).pop(saved);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = '저장하지 못했어요. 서버 연결을 확인한 뒤 다시 시도해 주세요.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_saving,
      child: AlertDialog(
        title: const Text('보호자·대상자 정보 수정'),
        content: SizedBox(
          width: 400,
          child: SingleChildScrollView(
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TextFormField(
                    key: const ValueKey('guardian-name-field'),
                    controller: _guardianName,
                    enabled: !_saving,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: '보호자 이름',
                      hintText: '보호자 본인의 이름',
                    ),
                    validator: _validateName,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const ValueKey('patient-name-field'),
                    controller: _patientName,
                    enabled: !_saving,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: '돌봄 대상자 이름',
                      hintText: '돌봄을 받는 분의 이름',
                      helperText: '이름을 바꿔도 연결된 기기와 알림은 유지됩니다.',
                      helperMaxLines: 2,
                    ),
                    validator: _validateName,
                  ),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    key: const ValueKey('guardian-relationship-field'),
                    initialValue: _relationship,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: '보호자는 대상자와 어떤 관계인가요?',
                      helperText: '예: 내가 대상자의 딸이면 ‘딸’을 선택하세요.',
                      helperMaxLines: 2,
                    ),
                    items:
                        {
                              '': '나중에 설정',
                              '아들': '아들',
                              '딸': '딸',
                              '손자': '손자',
                              '손녀': '손녀',
                              '배우자': '배우자',
                              '형제·자매': '형제·자매',
                              '기타': '기타 가족 / 보호자',
                              if (!const [
                                '',
                                '아들',
                                '딸',
                                '손자',
                                '손녀',
                                '배우자',
                                '형제·자매',
                                '기타',
                              ].contains(_relationship))
                                _relationship: _relationship,
                            }.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                    onChanged: _saving
                        ? null
                        : (value) {

                            setState(() => _relationship = value ?? '');
                          },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const ValueKey('patient-call-name-field'),
                    controller: _patientCallName,
                    enabled: !_saving,
                    maxLength: 40,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: 'TTS에서 대상자를 부르는 호칭',
                      hintText: '예: 엄마, 아빠, 할머니',
                      helperText: '직접 수정할 수 있어요. 비워두면 기존 TTS 기본 호칭을 유지합니다.',
                      helperMaxLines: 3,
                    ),
                    onChanged: (_) => setState(() {}),
                    validator: (value) {
                      final callName = value?.trim() ?? '';
                      if (callName.length > 40) return '호칭은 40자 이내로 입력해 주세요.';
                      if (RegExp(r'[\x00-\x1f\x7f]').hasMatch(callName)) {
                        return '호칭은 줄바꿈 없이 입력해 주세요.';
                      }
                      return null;
                    },
                  ),
                  if (_suggestedCallNames.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: _suggestedCallNames
                          .map(
                            (callName) => ActionChip(
                              label: Text(callName),
                              onPressed: _saving
                                  ? null
                                  : () {
                                      setState(
                                        () => _patientCallName.text = callName,
                                      );
                                    },
                            ),
                          )
                          .toList(),
                    ),
                  ],
                  if (_patientCallName.text.trim().isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      '문장 예시: “${_patientCallName.text.trim()}, 잠깐 쉬었다가 해요.”',
                    ),
                  ],
                  const SizedBox(height: 8),
                  const Text(
                    '저장하면 Render에 반영됩니다. 실제 발화에는 TTS 모듈의 호칭 연동이 필요하며, 목소리를 다시 학습하지 않아도 됩니다.',
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _phone,
                    enabled: !_saving,
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.done,
                    decoration: const InputDecoration(
                      labelText: '보호자 전화번호 (선택)',
                    ),
                    validator: (value) {
                      final phone = value?.trim() ?? '';
                      if (phone.isEmpty) return null;
                      final digits = phone.replaceAll(RegExp(r'\D'), '');
                      return phone.length > 30 || digits.length < 8
                          ? '전화번호를 확인해 주세요.'
                          : null;
                    },
                    onFieldSubmitted: (_) => _save(),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.of(context).pop(),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('저장'),
          ),
        ],
      ),
    );
  }
}
