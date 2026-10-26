import 'package:flutter/material.dart';

import '../models/home_environment.dart';
import '../repositories/guardian_repository.dart';
import '../services/home_region_catalog.dart';


class HomeRegionPage extends StatefulWidget {
  const HomeRegionPage({
    super.key,
    required this.repository,
    required this.initial,
    required this.onSaved,
    this.onSkip,
  });
  final GuardianRepository repository;
  final HomeEnvironment initial;
  final ValueChanged<HomeEnvironment> onSaved;
  final VoidCallback? onSkip;

  @override
  State<HomeRegionPage> createState() => _HomeRegionPageState();
}

class _HomeRegionPageState extends State<HomeRegionPage> {
  List<HomeRegion>? _regions;
  String? _province, _city, _district;
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final region = widget.initial.region;
    _province = region?.province;
    _city = region?.city;
    _district = region?.district;
    _loadRegions();
  }

  Future<void> _loadRegions() async {
    setState(() => _error = null);
    try {
      final regions = await HomeRegionCatalog.load();
      if (mounted) setState(() => _regions = regions);
    } catch (_) {
      if (mounted) setState(() => _error = '지역 목록을 불러오지 못했습니다. 다시 시도해 주세요.');
    }
  }

  HomeRegion? get _selectedRegion {
    if (_province == null || _city == null || _district == null) return null;
    for (final region in _regions ?? <HomeRegion>[]) {
      if (region.province == _province &&
          region.city == _city &&
          region.district == _district) {
        return region;
      }
    }
    return null;
  }

  Future<void> _save() async {
    final region = _selectedRegion;
    if (_saving || region == null) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final saved = await widget.repository.updateHomeEnvironment(
        regionCode: region.code,
        autoLightingEnabled: widget.initial.autoLightingEnabled,
      );
      if (mounted) widget.onSaved(saved);
    } catch (_) {
      if (mounted) {
        setState(() => _error = '지역을 저장하지 못했습니다. 서버 연결을 확인한 뒤 다시 저장해 주세요.');
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _dropdown(
    String label,
    String? value,
    List<String> values,
    ValueChanged<String?> changed,
  ) {
    return DropdownButtonFormField<String>(
      key: ValueKey('$label:$value:${values.join(',')}'),
      initialValue: values.contains(value) ? value : null,
      isExpanded: true,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
      ),
      items: values
          .map(
            (v) => DropdownMenuItem(
              value: v,
              child: Text(
                v.isEmpty ? '해당 없음 · 상위 지역 기준' : v,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          )
          .toList(),
      onChanged: _saving || values.isEmpty ? null : changed,
    );
  }

  @override
  Widget build(BuildContext context) {
    final regions = _regions ?? <HomeRegion>[];
    final provinces = regions.map((r) => r.province).toSet().toList();
    final cityRegions = regions.where((r) => r.province == _province).toList();
    final cities = cityRegions
        .map((r) => r.city)
        .where((v) => v.isNotEmpty)
        .toSet()
        .toList();
    if (_province != null && cities.isEmpty) cities.add('');
    final districts = cityRegions
        .where((r) => r.city == _city)
        .map((r) => r.district)
        .where((v) => v.isNotEmpty)
        .toSet()
        .toList();
    if (_city != null && districts.isEmpty) districts.add('');
    final selected = _selectedRegion;
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        appBar: AppBar(title: const Text('거주 지역 설정')),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Icon(
                  Icons.home_outlined,
                  size: 48,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 20),
                Text(
                  '돌봄 대상자가 사는 곳을 알려 주세요',
                  style: Theme.of(context).textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                const Text(
                  '자동 조명에 사용할 날씨 지역을 정하기 위한 정보입니다. 보호자님의 현재 위치가 아니라 돌봄 대상자가 실제로 사는 지역을 선택해 주세요. 상세 번지나 동·호수는 입력하지 않아도 됩니다.',
                  style: TextStyle(height: 1.6),
                ),
                const SizedBox(height: 28),
                if (_regions == null && _error == null)
                  const Center(child: CircularProgressIndicator()),
                if (_regions != null) ...[
                  _dropdown(
                    '시·도',
                    _province,
                    provinces,
                    (value) => setState(() {
                      _province = value;
                      _city = null;
                      _district = null;
                      if (!regions.any(
                        (r) => r.province == value && r.city.isNotEmpty,
                      )) {
                        _city = '';
                      }
                      if (_city == '' &&
                          !regions.any(
                            (r) => r.province == value && r.district.isNotEmpty,
                          )) {
                        _district = '';
                      }
                    }),
                  ),
                  const SizedBox(height: 18),
                  _dropdown(
                    '시·군·구',
                    _city,
                    cities,
                    (value) => setState(() {
                      _city = value;
                      _district = null;
                      if (!cityRegions.any(
                        (r) => r.city == value && r.district.isNotEmpty,
                      )) {
                        _district = '';
                      }
                    }),
                  ),
                  const SizedBox(height: 18),
                  _dropdown(
                    '읍·면·동',
                    _district,
                    districts,
                    (value) => setState(() => _district = value),
                  ),
                  const SizedBox(height: 20),
                  if (selected != null)
                    Text(
                      '선택한 지역: ${selected.label}',
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  const SizedBox(height: 12),
                  const Card(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: Text(
                        '선택한 지역은 서버에 저장되며, 연결된 조명 장치가 주기적으로 읽어 날씨·조명 제어에 사용합니다. 지역 저장은 조명 전원이나 밝기를 즉시 바꾸는 명령이 아닙니다.',
                        style: TextStyle(height: 1.5),
                      ),
                    ),
                  ),
                ],
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                const SizedBox(height: 20),
                if (_regions == null && _error != null)
                  OutlinedButton(
                    onPressed: _loadRegions,
                    child: const Text('지역 목록 다시 불러오기'),
                  ),
                FilledButton(
                  onPressed: _saving || selected == null ? null : _save,
                  child: Text(_saving ? '서버에 저장하는 중…' : '지역 저장하고 계속'),
                ),
                if (widget.onSkip != null)
                  TextButton(
                    onPressed: _saving ? null : widget.onSkip,
                    child: const Text('나중에 설정하고 홈으로'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
