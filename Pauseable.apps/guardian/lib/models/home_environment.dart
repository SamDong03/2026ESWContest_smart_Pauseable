class HomeRegion {
  const HomeRegion({
    required this.code,
    required this.province,
    required this.city,
    required this.district,
    required this.nx,
    required this.ny,
    required this.latitude,
    required this.longitude,
  });

  factory HomeRegion.fromJson(Map<String, dynamic> json) => HomeRegion(
    code: json['code'] as String,
    province: json['province'] as String,
    city: json['city'] as String,
    district: json['district'] as String,
    nx: json['nx'] as int,
    ny: json['ny'] as int,
    latitude: (json['latitude'] as num).toDouble(),
    longitude: (json['longitude'] as num).toDouble(),
  );

  final String code, province, city, district;
  final int nx, ny;
  final double latitude, longitude;

  String get label =>
      [province, city, district].where((s) => s.isNotEmpty).join(' ');
}

class HomeEnvironment {
  const HomeEnvironment({
    this.region,
    this.autoLightingEnabled = false,
    this.lightingStatus = 'region_required',
  });

  factory HomeEnvironment.fromJson(Map<String, dynamic> json) =>
      HomeEnvironment(
        region: json['region'] == null
            ? null
            : HomeRegion.fromJson(json['region'] as Map<String, dynamic>),
        autoLightingEnabled: json['auto_lighting_enabled'] as bool,
        lightingStatus:
            (json['lighting'] as Map<String, dynamic>)['status'] as String,
      );

  final HomeRegion? region;
  final bool autoLightingEnabled;
  final String lightingStatus;

  String get statusLabel =>
      region == null ? '자동 조명에 사용할 거주 지역을 선택해 주세요' : '자동 조명용 지역 저장됨';
}
