/// 카카오맵 링크 생성.
///
/// 국내에서는 구글 지도가 지도 데이터 반출 규제 탓에 도보·자동차 경로를 사실상
/// 내주지 못한다. 여행자가 실제로 길을 찾을 수 있는 쪽은 카카오라 여기로 넘긴다.
/// 모바일에서는 카카오맵 앱이 설치돼 있으면 앱으로, 없으면 웹으로 열린다.
library;

import 'package:latlong2/latlong.dart';

const _host = 'map.kakao.com';

/// 카카오가 지원하는 경로 수단.
///
/// `public`(대중교통)은 일부러 없다 — 실측해보면 카카오가 조용히 `car` 로
/// 떨어뜨려서, 대중교통을 골랐는데 자동차 경로가 열린다.
enum KakaoRouteMode {
  car,
  walk;

  String get slug => name;
}

/// 출발지 → 도착지 길찾기 링크.
///
/// 카카오는 경로 세그먼트를 **순서로** 읽는다. 출발지가 먼저, 도착지가 나중.
/// 이름에 쉼표가 있으면 좌표 구분자로 오해하므로 인코딩해서 넘긴다.
Uri kakaoRoute({
  required LatLng from,
  required LatLng to,
  required String toName,
  required KakaoRouteMode mode,
  String fromName = 'My location',
}) {
  final dest = toName.trim().isEmpty ? 'Destination' : toName.trim();
  // Uri.https 는 쉼표를 경로에서 유효한 문자로 보고 그냥 둔다. 그러면 이름 안의
  // 쉼표('고려대학교병원, 안암')를 카카오가 좌표 구분자로 읽어 길찾기가 깨지므로
  // 이름만 encodeComponent 로 미리 %2C 까지 인코딩해 넣는다.
  return Uri.parse('https://$_host/link/by/${mode.slug}/'
      '${Uri.encodeComponent(fromName)},${from.latitude},${from.longitude}/'
      '${Uri.encodeComponent(dest)},${to.latitude},${to.longitude}');
}

/// 좌표 없이 문자열로만 찾을 때. 대사관 카드처럼 주소만 있는 경우에 쓴다.
Uri kakaoSearch(String query) =>
    Uri.parse('https://$_host/link/search/${Uri.encodeComponent(query.trim())}');
