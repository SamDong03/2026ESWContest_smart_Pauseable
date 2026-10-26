import 'dart:convert';

import 'package:flutter/services.dart';

import '../models/home_environment.dart';

class HomeRegionCatalog {
  static List<HomeRegion>? _cached;
  static Future<List<HomeRegion>> load() async {
    final cached = _cached;
    if (cached != null) return cached;
    final data = jsonDecode(
      await rootBundle.loadString('assets/data/kma_regions.json'),
    ) as Map<String, dynamic>;
    return _cached = List<HomeRegion>.unmodifiable(
      (data['regions'] as List)
          .map((row) => HomeRegion.fromJson(row as Map<String, dynamic>))
          .toList(),
    );
  }
}
