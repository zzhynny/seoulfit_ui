import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import '../config/api_base.dart';
import '../models/live_help.dart';

/// 위치 거부/실패 시 고를 수 있는 지역들. 백엔드 geo.py 의 SEOUL_AREA_CENTERS
/// 중 여행자가 실제로 머무는 곳만 추렸다.
const kSeoulAreas = <String, LatLng>{
  'Hongdae': LatLng(37.5563, 126.9227),
  'Myeongdong': LatLng(37.5636, 126.9857),
  'Gangnam': LatLng(37.4979, 127.0276),
  'Itaewon': LatLng(37.5347, 126.9946),
  'Jongno': LatLng(37.5729, 126.9794),
  'Seongsu': LatLng(37.5447, 127.0558),
  'Yeouido': LatLng(37.5217, 126.9244),
  'Jamsil': LatLng(37.5133, 127.1028),
};

/// 여행 중 도우미의 데이터 접근. 대사관은 번들 에셋, 나머지 둘은 백엔드다.
class LiveHelpService {
  static List<Embassy>? _embassies;

  static String get _base => apiBase;

  /// 번들된 주한공관 118건. 첫 호출에만 파싱하고 이후 메모리 캐시를 쓴다.
  /// 네트워크를 타지 않으므로 데이터로밍이 끊겨도 동작한다.
  static Future<List<Embassy>> loadEmbassies() async {
    final cached = _embassies;
    if (cached != null) return cached;
    final raw = await rootBundle.loadString('assets/data/embassies.json');
    final list = jsonDecode(raw) as List;
    final parsed = [
      for (final e in list)
        if (e is Map) Embassy.fromJson(Map<String, dynamic>.from(e)),
    ];
    _embassies = parsed;
    return parsed;
  }

  /// 현재 좌표. 권한 거부·서비스 비활성·타임아웃이면 null 을 돌려주고,
  /// 호출부가 지역 수동 선택으로 넘어간다. 예외를 던지지 않는다 —
  /// 응급 화면에서 막다른 길을 만들지 않기 위해서다.
  static Future<LatLng?> currentLatLng() async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return null;
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        return null;
      }
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 8),
        ),
      );
      return LatLng(pos.latitude, pos.longitude);
    } catch (_) {
      return null;
    }
  }

  static Future<Map<String, dynamic>> _post(
      String path, Map<String, dynamic> body) async {
    final res = await http.post(
      Uri.parse('$_base/$path'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (res.statusCode != 200) {
      throw Exception('Backend error ${res.statusCode}: ${res.body}');
    }
    return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
  }

  /// Google Place 사진 한 장의 URL. 백엔드 프록시를 가리킨다.
  ///
  /// 구글 원본 URL(`.../place/photo?...&key=...`)을 그대로 쓰면 Places 키가
  /// 앱 트래픽에 그대로 실린다. 백엔드가 서버에서 받아 바이트만 돌려주므로
  /// 키는 서버 밖으로 나가지 않는다. [width] 는 서버가 100~800 으로 자른다.
  static String placePhotoUrl(String photoRef, {int width = 400}) =>
      '$_base/place-photo?ref=${Uri.encodeQueryComponent(photoRef)}&w=$width';

  /// 도보권 카페/음식점. [type] 은 Google Places 타입 (`cafe`, `restaurant`).
  static Future<List<NearbyPlace>> fetchNearby(LatLng at, String type) async {
    final json = await _post('nearby', {
      'lat': at.latitude,
      'lng': at.longitude,
      'type': type,
      'want': 5,
    });
    final list = json['places'] as List? ?? const [];
    return [
      for (final p in list)
        if (p is Map) NearbyPlace.fromJson(Map<String, dynamic>.from(p)),
    ];
  }

  /// 가까운 운영 중 응급실. 거리순으로 이미 정렬되어 온다.
  static Future<List<EmergencyRoom>> fetchEmergencyRooms(LatLng at) async {
    final json = await _post('emergency-rooms', {
      'lat': at.latitude,
      'lng': at.longitude,
      'want': 5,
    });
    final list = json['hospitals'] as List? ?? const [];
    return [
      for (final h in list)
        if (h is Map) EmergencyRoom.fromJson(Map<String, dynamic>.from(h)),
    ];
  }

  /// 주변 관광 POI 를 거리순으로. [category] 가 null 이면 전체(칩의 'All').
  ///
  /// 반경 인자가 없다 — 서버가 반경으로 자르지 않고 상위 [want] 건을 준다.
  /// POI 밀도가 지역마다 10배 넘게 차이나서 반경을 고정하면 빈 화면이 나온다.
  static Future<List<TourPoi>> fetchTourPois(
    LatLng at, {
    String? category,
    int want = 20,
  }) async {
    final json = await _post('nearby-poi', {
      'lat': at.latitude,
      'lng': at.longitude,
      'category': category,
      'want': want,
    });
    final list = json['pois'] as List? ?? const [];
    return [
      for (final p in list)
        if (p is Map) TourPoi.fromJson(Map<String, dynamic>.from(p)),
    ];
  }

  /// 주변 쇼핑 POI 를 거리순으로. [category] 가 null 이면 전체(칩의 'All').
  ///
  /// fetchTourPois 와 같은 계약이다 — 서버가 반경으로 자르지 않고 상위 [want]
  /// 건을 준다. 면세점(DF)은 전체 5건뿐이라 몇 km 짜리가 나올 수 있다.
  static Future<List<ShoppingPoi>> fetchShoppingPois(
    LatLng at, {
    String? category,
    int want = 20,
  }) async {
    final json = await _post('nearby-shopping', {
      'lat': at.latitude,
      'lng': at.longitude,
      'category': category,
      'want': want,
    });
    final list = json['pois'] as List? ?? const [];
    return [
      for (final p in list)
        if (p is Map) ShoppingPoi.fromJson(Map<String, dynamic>.from(p)),
    ];
  }
}
