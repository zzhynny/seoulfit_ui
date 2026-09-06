/// 여행 중 도우미 네 기능의 데이터 모델.
///
/// [Embassy] 는 앱에 번들된 assets/data/embassies.json 에서, 나머지 셋은
/// 백엔드 /nearby · /emergency-rooms · /nearby-poi 응답에서 온다.
library;

String _str(Object? v) => v is String ? v : '';
double _dbl(Object? v) => v is num ? v.toDouble() : 0;
int _int(Object? v) => v is num ? v.toInt() : 0;

/// 주한 공관 한 곳. 서울 소재 118건이 앱에 번들되어 있어 오프라인에서도 읽힌다.
class Embassy {
  final String countryEn;
  final String countryKo;
  final String iso2;
  final String missionKo;
  final String addressKo;
  final String postalCode;

  /// 외교부 원문 그대로. `788-2100/1` 처럼 복수 번호일 수 있어 표시 전용이다.
  final String phone;

  /// `tel:` 링크용으로 지역번호를 채워 정규화한 단일 번호. 비어 있을 수 있다.
  final String phoneDial;

  final String email;

  /// 118건 중 15건만 값이 있다. 비어 있으면 링크 버튼을 숨긴다.
  final String website;

  const Embassy({
    required this.countryEn,
    required this.countryKo,
    required this.iso2,
    required this.missionKo,
    required this.addressKo,
    required this.postalCode,
    required this.phone,
    required this.phoneDial,
    required this.email,
    required this.website,
  });

  factory Embassy.fromJson(Map<String, dynamic> j) => Embassy(
        countryEn: _str(j['country_en']),
        countryKo: _str(j['country_ko']),
        iso2: _str(j['iso2']),
        missionKo: _str(j['mission_ko']),
        addressKo: _str(j['address_ko']),
        postalCode: _str(j['postal_code']),
        phone: _str(j['phone']),
        phoneDial: _str(j['phone_dial']),
        email: _str(j['email']),
        website: _str(j['website']),
      );

  /// 영문명·한글명·ISO2·주소 어느 쪽으로 쳐도 찾히게 한다. 여행자는 자기 나라를
  /// 영어로 치지만 한국인 동행이 한글로 칠 수도 있다.
  bool matches(String query) {
    final q = query.trim().toLowerCase();
    if (q.isEmpty) return true;
    return countryEn.toLowerCase().contains(q) ||
        countryKo.contains(q) ||
        iso2.toLowerCase() == q ||
        missionKo.contains(q) ||
        addressKo.contains(q);
  }
}

/// 운영 중인 응급실 한 곳. 위치조회와 실시간 병상을 hpid 로 조인한 결과다.
class EmergencyRoom {
  final String name;
  final String address;
  final double lat;
  final double lng;
  final double distanceKm;

  /// 응급실 직통번호. 병원 대표번호가 아니라 새벽에도 받는 번호다.
  final String erPhone;

  /// 가용 병상. 정원 초과를 음수로 표현하므로 [isFull] 이 아닐 때만 렌더링한다.
  final int beds;
  final String bedsState;
  final String updatedAt;

  const EmergencyRoom({
    required this.name,
    required this.address,
    required this.lat,
    required this.lng,
    required this.distanceKm,
    required this.erPhone,
    required this.beds,
    required this.bedsState,
    required this.updatedAt,
  });

  factory EmergencyRoom.fromJson(Map<String, dynamic> j) => EmergencyRoom(
        name: _str(j['name']),
        address: _str(j['address']),
        lat: _dbl(j['lat']),
        lng: _dbl(j['lng']),
        distanceKm: _dbl(j['distance_km']),
        erPhone: _str(j['er_phone']),
        beds: _int(j['beds']),
        bedsState: _str(j['beds_state']),
        updatedAt: _str(j['updated_at']),
      );

  /// Self-sufficient on purpose: `hvec` encodes over-capacity as a negative
  /// number, so a `beds_state` that is neither `'full'` nor `'unknown'` (e.g.
  /// `''` from a missing key under app/backend version skew) must still be
  /// treated as full rather than falling through to a `'-6 beds'` render.
  bool get isFull => bedsState == 'full' || beds <= 0;
}

/// 주변 추천 장소 한 곳.
class NearbyPlace {
  final String name;
  final String address;
  final double lat;
  final double lng;
  final int distanceM;

  /// 리뷰가 없는 업소는 구글이 평점을 아예 주지 않는다. null 이면 뱃지를 숨긴다.
  final double? rating;
  final int reviews;

  /// 결측 가능. null 이면 영업 상태 뱃지를 숨긴다.
  final bool? openNow;

  final String placeId;

  /// Google Place Photos 참조. 사진 URL 은 Places 키를 쿼리에 달아야 열려서
  /// 앱에는 이 참조만 온다 — 이미지는 백엔드 `/place-photo` 가 대신 받아
  /// 준다. 20건 중 19건에 있고, 비어 있으면 카드가 사진 자리를 접는다.
  final String photoRef;

  const NearbyPlace({
    required this.name,
    required this.address,
    required this.lat,
    required this.lng,
    required this.distanceM,
    required this.rating,
    required this.reviews,
    required this.openNow,
    required this.placeId,
    required this.photoRef,
  });

  factory NearbyPlace.fromJson(Map<String, dynamic> j) => NearbyPlace(
        name: _str(j['name']),
        address: _str(j['address']),
        lat: _dbl(j['lat']),
        lng: _dbl(j['lng']),
        distanceM: _int(j['distance_m']),
        rating: j['rating'] is num ? (j['rating'] as num).toDouble() : null,
        reviews: _int(j['reviews']),
        openNow: j['open_now'] is bool ? j['open_now'] as bool : null,
        placeId: _str(j['place_id']),
        photoRef: _str(j['photo_ref']),
      );
}

/// 주변 관광 POI 한 곳. 백엔드 `/nearby-poi` 응답이며, 한국관광공사 TourAPI
/// 사전 수집분(서울 431건)에서 온다.
///
/// 목록 표시와 상세 시트가 같은 객체를 쓴다 — 서버가 상세까지 한 응답에
/// 담아주므로 카드를 열 때 추가 호출이 없다.
class TourPoi {
  final String id;
  final String title;

  /// 한국관광공사 대분류 코드(`VE`/`EX`/`HS`/`NA`/`LS`/`AC`).
  /// 마커·칩 색을 고르는 키라 표시용 이름과 분리해 둔다.
  final String category;

  final String address;
  final double lat;
  final double lng;
  final int distanceM;

  /// 431건 중 313건만 있다. 비어 있으면 플레이스홀더를 그린다.
  final String image;

  /// 영문 소개. 평균 600자라 카드가 아니라 상세 시트에서만 펼친다.
  final String overview;

  /// 아래 여섯은 결측이 흔하다. 비어 있으면 그 줄을 통째로 숨긴다.
  final String hours;
  final String closed;
  final String fee;
  final String parking;
  final String tel;
  final String homepage;

  const TourPoi({
    required this.id,
    required this.title,
    required this.category,
    required this.address,
    required this.lat,
    required this.lng,
    required this.distanceM,
    required this.image,
    required this.overview,
    required this.hours,
    required this.closed,
    required this.fee,
    required this.parking,
    required this.tel,
    required this.homepage,
  });

  factory TourPoi.fromJson(Map<String, dynamic> j) => TourPoi(
        id: _str(j['id']),
        title: _str(j['title']),
        category: _str(j['category']),
        address: _str(j['address']),
        lat: _dbl(j['lat']),
        lng: _dbl(j['lng']),
        distanceM: _int(j['distance_m']),
        image: _str(j['image']),
        overview: _str(j['overview']),
        hours: _str(j['hours']),
        closed: _str(j['closed']),
        fee: _str(j['fee']),
        parking: _str(j['parking']),
        tel: _str(j['tel']),
        homepage: _str(j['homepage']),
      );

  /// TourAPI 제목은 `English (한글)` 형식이다. 영문 UI 라 괄호 앞만 쓴다.
  String get name {
    final i = title.indexOf(' (');
    return i > 0 ? title.substring(0, i) : title;
  }

  /// 1km 미만은 미터로, 그 이상은 소수 한 자리 km 로. 관광 POI 는 반경 제한이
  /// 없어 6km 짜리도 나오므로 거리 표기가 정직해야 한다.
  String get distanceLabel => distanceM < 1000
      ? '$distanceM m'
      : '${(distanceM / 1000).toStringAsFixed(1)} km';
}

/// 주변 쇼핑 POI 한 곳. 백엔드 `/nearby-shopping` 응답이며 서울관광재단
/// Visit Seoul API 수집분(dataset/shopping_poi.json)에서 온다.
///
/// 서울관광재단이 골라 쓴 '가볼 만한 쇼핑 장소' 310건. 전량에 좌표·설명문·
/// 대표 이미지가 있고 영업시간은 285/310, 지하철 안내는 308/310 에 있다.
class ShoppingPoi {
  final String id;
  final String title;

  /// Visit Seoul 하위 분류 코드(`SP`/`TM`/`MO`/`DS`/`DF`/`SW`).
  /// 마커·칩 색을 고르는 키라 표시용 이름과 분리해 둔다.
  final String category;

  final String address;
  final double lat;
  final double lng;
  final int distanceM;

  /// 310건 전량에 있다.
  final String image;

  /// 한 줄 소개. 카드 부제로 쓴다.
  final String summary;

  /// 본문. HTML 은 빌드 단계에서 걷어냈다.
  final String overview;

  /// 아래 넷은 결측이 있다. 비어 있으면 그 줄을 통째로 숨긴다.
  final String hours;
  final String tel;
  final String homepage;
  final String subway;

  const ShoppingPoi({
    required this.id,
    required this.title,
    required this.category,
    required this.address,
    required this.lat,
    required this.lng,
    required this.distanceM,
    required this.image,
    required this.summary,
    required this.overview,
    required this.hours,
    required this.tel,
    required this.homepage,
    required this.subway,
  });

  factory ShoppingPoi.fromJson(Map<String, dynamic> j) => ShoppingPoi(
        id: _str(j['id']),
        title: _str(j['title']),
        category: _str(j['category']),
        address: _str(j['address']),
        lat: _dbl(j['lat']),
        lng: _dbl(j['lng']),
        distanceM: _int(j['distance_m']),
        image: _str(j['image']),
        summary: _str(j['summary']),
        overview: _str(j['overview']),
        hours: _str(j['hours']),
        tel: _str(j['tel']),
        homepage: _str(j['homepage']),
        subway: _str(j['subway']),
      );

  /// TourPoi 와 같은 규칙. 1km 미만은 미터, 그 이상은 소수 한 자리 km.
  /// 반경 제한이 없어 몇 km 짜리도 나오므로 표기가 정직해야 한다.
  String get distanceLabel => distanceM < 1000
      ? '$distanceM m'
      : '${(distanceM / 1000).toStringAsFixed(1)} km';
}
