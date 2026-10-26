import 'dart:math';

import 'package:flutter/material.dart';

import '../models/voice_consent_receipt.dart';
import '../repositories/guardian_repository.dart';


class VoiceRecordingConsentSheet extends StatefulWidget {
  const VoiceRecordingConsentSheet({super.key, required this.repository});

  final GuardianRepository repository;
  static const policyVersion = VoiceConsentReceipt.currentPolicyVersion;

  @override
  State<VoiceRecordingConsentSheet> createState() =>
      _VoiceRecordingConsentSheetState();
}

class _VoiceRecordingConsentSheetState
    extends State<VoiceRecordingConsentSheet> {
  bool _agreed = false;
  bool _saving = false;
  String? _error;

  late final String _requestId = List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> _saveConsent() async {
    if (!_agreed || _saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final receipt = await widget.repository.saveVoiceConsent(
        requestId: _requestId,
      );
      if (mounted) Navigator.pop(context, receipt);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error =
              '동의 기록을 서버에 저장하지 못했어요. 연결을 확인하고 다시 눌러 주세요. 녹음과 전송은 시작되지 않았어요.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      child: SingleChildScrollView(
        key: const ValueKey('voice-consent-scroll'),
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Icon(Icons.privacy_tip_outlined, size: 36, color: colors.primary),
            const SizedBox(height: 12),
            Text(
              '보호자 음성 수집·이용 동의',
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            const Text(
              '녹음 전에 아래 내용을 확인해 주세요. 본인이 직접 녹음하는 목소리에 대해 동의해 주세요. 동의 전에는 마이크를 사용하거나 녹음 파일을 전송하지 않습니다.',
              style: TextStyle(height: 1.5),
            ),
            _section(
              '수집·이용 목적과 항목',
              '돌봄 대상자에게 보호자 목소리로 안내하는 TTS를 학습·생성하기 위해 사용합니다. '
                  '녹음 WAV, 대본·문장 번호, 녹음 길이, 학습 세트와 대상자 식별값을 처리하며, '
                  '이 과정에서 학습된 음성 모델과 처리 기록이 생성됩니다.',
            ),
            _section(
              '외부 서버 처리·저장',
              '녹음은 Render API 서버를 거쳐 Cloudflare R2 저장소에 보관되고 팀 음성학습 서버에서 처리됩니다. '
                  '학습된 모델은 저장소와 환자 측 Raspberry Pi 장비에서 음성 안내에 사용됩니다. '
                  '각 문장의 녹음을 완료하면 해당 WAV가 자동 전송되며, 실패한 파일을 다시 전송할 수도 있습니다.',
            ),
            _section(
              '원본 녹음·중간 학습 산출물',
              '장비의 모델 설치·합성 검증 성공 확인 후 24시간 또는 해당 학습 세트 생성 후 14일 중 '
                  '먼저 도래한 시점을 삭제 기한으로 삼습니다. 학습이 끝나지 않거나 장비의 성공 확인이 없어도 '
                  '학습 세트 생성 후 14일이 지나면 삭제 대상이 됩니다.',
            ),
            _section(
              '학습 서버의 임시 복사본',
              'GPU 학습 서버에 내려받은 녹음, 체크포인트와 결과 복사본은 성공·실패와 관계없이 '
                  '해당 작업 시도가 끝나면 삭제하도록 되어 있습니다.',
            ),
            _section(
              '학습된 목소리 모델은 별도 보관',
              '현재 사용하는 모델은 다음 모델로 검증·교체될 때까지 유지합니다. '
                  '교체된 이전 모델은 복구를 위한 7일 보관 기간 후 삭제 대상이 됩니다. '
                  '원본 녹음 삭제가 학습된 모델의 즉시 삭제를 뜻하지는 않습니다.',
            ),
            _section(
              '삭제 처리 시점과 남는 기록',
              '서버는 시작할 때와 실행 중 매시간 삭제 기한을 확인합니다. '
                  '서버 휴면이나 일시적 오류로 실제 삭제가 늦어질 수 있습니다. '
                  '음성 파일 삭제 후에도 학습 작업 ID, 처리 시각, 해시 등 비음성 관리 기록은 남습니다.',
            ),
            _section(
              '동의 기록 보관',
              '동의 버튼을 누르면 대상자 식별값, 동의 시각, 안내문 버전과 동의 여부를 서버에 별도 저장합니다. '
                  '녹음 파일 삭제 후에도 이 비음성 관리 기록은 남으며 현재 자동 삭제 기한은 설정되어 있지 않습니다. '
                  '기록 저장이 확인되어야 녹음 화면이 열립니다.',
            ),
            _section(
              '동의를 거부할 권리',
              '동의하지 않으면 보호자 음성 녹음·전송을 진행할 수 없습니다. '
                  '기존 알림 수신, 출입 사진 확인과 다른 앱 기능은 그대로 이용할 수 있습니다. '
                  '돌아가기를 누르는 것은 이미 전송된 데이터의 삭제나 기존 동의 철회 요청을 의미하지 않습니다.',
            ),
            const SizedBox(height: 12),
            CheckboxListTile(
              key: const ValueKey('voice-consent-checkbox'),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _agreed,
              onChanged: _saving
                  ? null
                  : (value) => setState(() => _agreed = value == true),
              title: const Text('위 내용을 확인하고 본인 음성의 수집·이용에 동의합니다.'),
              subtitle: const Text(
                '음성학습을 이용할 때만 필요하며, 선택하지 않아도 다른 기능은 이용할 수 있어요.',
              ),
            ),
            const SizedBox(height: 12),
            if (_error != null)
              Semantics(
                liveRegion: true,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(_error!, style: TextStyle(color: colors.error)),
                ),
              ),
            FilledButton(
              key: const ValueKey('voice-consent-continue'),
              onPressed: _agreed && !_saving ? _saveConsent : null,
              child: Text(_saving ? '동의 기록 저장 중…' : '동의하고 녹음 화면으로'),
            ),
            const SizedBox(height: 6),
            TextButton(
              key: const ValueKey('voice-consent-decline'),
              onPressed: _saving ? null : () => Navigator.pop(context),
              child: const Text('동의하지 않고 돌아가기'),
            ),
            const SizedBox(height: 10),
            Text(
              '동의 기록은 서버에 보관하며, 녹음 화면에 다시 들어올 때 재확인합니다.\n안내문 버전: ${VoiceRecordingConsentSheet.policyVersion}',
              style: Theme.of(context).textTheme.bodySmall
                  ?.copyWith(color: colors.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }

  Widget _section(String title, String body) => Padding(
    padding: const EdgeInsets.only(top: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 6),
        Text(body, style: const TextStyle(height: 1.5)),
      ],
    ),
  );
}
