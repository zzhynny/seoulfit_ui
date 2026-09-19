import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/chat.dart';
import '../../models/live_help.dart';
import '../../services/kakao_links.dart';
import '../../services/live_help_service.dart';
import '../../theme/theme.dart';
import '../../widgets/animations.dart';
import '../../widgets/data_source_note.dart';

/// Explore 칩. `null` 은 전체이고, 나머지는 한국관광공사 대분류 코드다.
/// 단일선택이라 항상 정확히 하나가 켜져 있다 — 다중선택이면 'All' 이
/// "전부 켜기"인지 "필터 해제"인지 규칙을 하나 더 만들어야 한다.
const _kTourCategories = <(String?, String)>[
  (null, 'All'),
  ('VE', 'Culture'),
  ('EX', 'Experience'),
  ('HS', 'History'),
  ('NA', 'Nature'),
  ('LS', 'Leisure'),
  ('AC', 'Stay'),
];

/// One of the on-trip help destinations, rendered without the Flutter app's
/// own chrome: SeoulFit's tab shell already supplies the status bar, bottom
/// nav and Plan/On-Trip toggle, and the hub is the Chat tab's own On-Trip
/// view rather than a second list of action cards.
///
/// None of these views call an LLM. They are fixed lookups on purpose —
/// in an emergency neither latency nor a hallucination is acceptable.
class LiveHelpTopicScreen extends StatelessWidget {
  const LiveHelpTopicScreen({
    super.key,
    required this.topic,
    required this.onBack,
  });

  final LiveHelpTopic topic;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.sm, AppSpacing.sm, AppSpacing.lg, 0),
          child: Row(
            children: [
              IconButton(
                onPressed: onBack,
                icon: const Icon(Icons.chevron_left, size: 28),
                color: AppColors.textPrimary,
              ),
              Expanded(
                child: Text(
                  _title(topic),
                  style: AppTextStyles.headingSmall.copyWith(fontSize: 18),
                ),
              ),
            ],
          ),
        ),
        Expanded(child: _body(topic)),
      ],
    );
  }
}

String _title(LiveHelpTopic topic) {
  switch (topic) {
    case LiveHelpTopic.passport:
      return 'Lost passport';
    case LiveHelpTopic.emergency:
      return 'Emergency room';
    case LiveHelpTopic.nearby:
      return 'Near me';
    case LiveHelpTopic.explore:
      return 'Explore nearby';
    case LiveHelpTopic.shopping:
      return 'Shopping';
  }
}

Widget _body(LiveHelpTopic topic) {
  switch (topic) {
    case LiveHelpTopic.passport:
      // The embassy list ships in assets/data/embassies.json, so this one
      // needs no location fix and works with the radio off.
      return const _PassportView();
    case LiveHelpTopic.emergency:
      return _LocationGate(builder: (at) => _EmergencyView(at));
    case LiveHelpTopic.nearby:
      return _LocationGate(builder: (at) => _NearbyView(at));
    case LiveHelpTopic.explore:
      return _LocationGate(builder: (at) => _ExploreView(at));
    case LiveHelpTopic.shopping:
      return _LocationGate(builder: (at) => _ShoppingView(at));
  }
}

/// 앱 밖으로 나가는 모든 tap 의 공통 경로. 응급 화면은 어떤 경우에도 막다른
/// 길을 만들지 않는다 — 다이얼러가 없거나 launch 가 실패해도 사용자가 손으로
/// 옮겨 적을 수 있게 원본 값(전화번호/주소/URL)을 스낵바로 보여준다.
/// 출발지를 아는 경우에만 by/{mode} 경로를 만들고, 모르면 도착지 검색으로 떨어뜨린다.
/// 출발지 없이 by/ 스킴을 쓰면 카카오가 좌표 자리를 빈 값으로 읽어 경로가 깨진다.
Uri _routeTo(LatLng? from, LatLng to, String name, KakaoRouteMode mode) =>
    from == null
        ? kakaoSearch(
            name.trim().isEmpty ? '${to.latitude},${to.longitude}' : name)
        : kakaoRoute(from: from, to: to, toName: name, mode: mode);

Future<void> _launch(BuildContext context, Uri uri, String display) async {
  var ok = false;
  try {
    if (await canLaunchUrl(uri)) {
      ok = await launchUrl(uri);
    }
  } catch (_) {
    ok = false;
  }
  if (!ok && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(display)),
    );
  }
}

class _PassportView extends StatefulWidget {
  const _PassportView();

  @override
  State<_PassportView> createState() => _PassportViewState();
}

class _PassportViewState extends State<_PassportView> {
  final _controller = TextEditingController();
  // null while the bundled asset is still loading; distinguishes "loading"
  // from "loaded, zero matches" so the empty-state message doesn't flash
  // before the first frame the data actually arrives on.
  List<Embassy>? _all;
  String _query = '';

  @override
  void initState() {
    super.initState();
    LiveHelpService.loadEmbassies().then((v) {
      if (mounted) setState(() => _all = v);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final all = _all;
    final hits = all?.where((e) => e.matches(_query)).toList();
    return Column(
      children: [
        const _EmergencyNumbersBanner(),
        Padding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, AppSpacing.sm),
          child: TextField(
            controller: _controller,
            onChanged: (v) => setState(() => _query = v),
            style: AppTextStyles.sans(fontSize: 14, color: AppColors.textPrimary),
            decoration: InputDecoration(
              hintText: 'Search your country — Philippines, 필리핀, PH',
              hintStyle:
                  AppTextStyles.sans(fontSize: 13, color: AppColors.textSecondary),
              prefixIcon: const Icon(Icons.search_rounded, color: AppColors.textSecondary),
              filled: true,
              fillColor: AppColors.surface,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: AppColors.border),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: AppColors.border),
              ),
            ),
          ),
        ),
        Expanded(
          child: hits == null
              ? const Center(
                  child: CircularProgressIndicator(color: AppColors.primary),
                )
              : hits.isEmpty
                  ? Center(
                      child: Text('No embassy found for "$_query"',
                          style: AppTextStyles.sans(
                              fontSize: 13, color: AppColors.textSecondary)),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(
                          AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.xxl),
                      itemCount: hits.length,
                      separatorBuilder: (_, _) =>
                          const SizedBox(height: AppSpacing.smMd),
                      itemBuilder: (_, i) => _EmbassyCard(hits[i]),
                    ),
        ),
      ],
    );
  }
}

/// 여권 분실 시 실제로 통화가 되는 두 번호. 대사관 대표전화는 새벽에 받지
/// 않지만 이 둘은 24시간이다. 데이터에 긴급전화 필드가 아예 없어서 이 배너가
/// 그 구멍을 메운다.
class _EmergencyNumbersBanner extends StatelessWidget {
  const _EmergencyNumbersBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, 0),
      padding: const EdgeInsets.all(AppSpacing.smMd),
      decoration: BoxDecoration(
        color: AppColors.warningTint,
        border: Border.all(color: AppColors.warning),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Report to the police first, then your embassy.',
              style: AppTextStyles.sans(
                  fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
          const SizedBox(height: AppSpacing.sm),
          const Row(
            children: [
              Expanded(
                child: _PhonePill(
                  label: '1330 · 24h interpreter',
                  number: '1330',
                ),
              ),
              SizedBox(width: AppSpacing.sm),
              Expanded(
                child: _PhonePill(label: '112 · Police', number: '112'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PhonePill extends StatelessWidget {
  final String label;
  final String number;
  const _PhonePill({required this.label, required this.number});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => _launch(context, Uri(scheme: 'tel', path: number), number),
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.smMd, vertical: AppSpacing.sm),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.call_rounded, size: 14, color: AppColors.textPrimary),
            const SizedBox(width: 6),
            Flexible(
              child: Text(label,
                  overflow: TextOverflow.ellipsis,
                  style: AppTextStyles.sans(
                      fontSize: 11, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmbassyCard extends StatelessWidget {
  final Embassy e;
  const _EmbassyCard(this.e);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(e.countryEn,
              style: AppTextStyles.sans(
                  fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
          Text(e.countryKo,
              style:
                  AppTextStyles.sans(fontSize: 12, color: AppColors.textSecondary)),
          const SizedBox(height: AppSpacing.smMd),
          // 한글 주소를 그대로 노출한다 — 택시 기사에게 화면을 보여주는 용도다.
          Text(e.addressKo,
              style: AppTextStyles.sans(
                  fontSize: 13, color: AppColors.textPrimary, height: 1.4)),
          Text(e.addressEn,
              style: AppTextStyles.sans(
                  fontSize: 11.5, color: AppColors.textSecondary, height: 1.3)),
          const SizedBox(height: AppSpacing.smMd),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              if (e.phoneDial.isNotEmpty)
                _MiniButton(
                  icon: Icons.call_rounded,
                  label: e.phone,
                  onTap: () => _launch(
                      context,
                      Uri(scheme: 'tel', path: e.phoneDial.replaceAll('-', '')),
                      e.phone),
                ),
              _MiniButton(
                icon: Icons.map_outlined,
                label: 'Map',
                onTap: () =>
                    _launch(context, kakaoSearch(e.addressKo), e.addressKo),
              ),
              if (e.website.isNotEmpty)
                _MiniButton(
                  icon: Icons.language_rounded,
                  label: 'Website',
                  onTap: () =>
                      _launch(context, Uri.parse(e.website), e.website),
                ),
              if (e.email.isNotEmpty)
                _MiniButton(
                  icon: Icons.mail_outline_rounded,
                  label: 'Email',
                  onTap: () => _launch(
                      context, Uri(scheme: 'mailto', path: e.email), e.email),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _MiniButton(
      {required this.icon, required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.smMd, vertical: AppSpacing.sm),
        decoration: BoxDecoration(
          color: AppColors.primaryTint,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: AppColors.primary),
            const SizedBox(width: 6),
            Text(label,
                style: AppTextStyles.sans(
                    fontSize: 11.5, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
          ],
        ),
      ),
    );
  }
}

/// GPS 를 시도하고, 실패하면 지역 수동 선택을 띄운다.
/// 응급 화면이 막다른 길이 되지 않도록 항상 좌표를 확보하는 것이 목적이다.
class _LocationGate extends StatefulWidget {
  final Widget Function(LatLng at) builder;
  const _LocationGate({required this.builder});

  @override
  State<_LocationGate> createState() => _LocationGateState();
}

class _LocationGateState extends State<_LocationGate> {
  LatLng? _at;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    LiveHelpService.currentLatLng().then((v) {
      if (!mounted) return;
      setState(() {
        _at = v;
        _loading = false;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: AppColors.primary));
    }
    final at = _at;
    if (at != null) return widget.builder(at);
    return _AreaPicker(onPick: (v) => setState(() => _at = v));
  }
}

class _AreaPicker extends StatelessWidget {
  final ValueChanged<LatLng> onPick;
  const _AreaPicker({required this.onPick});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        Text("Couldn't get your location",
            style: AppTextStyles.sans(
                fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.textPrimary)),
        const SizedBox(height: AppSpacing.xs),
        Text('Pick the area you are in and I will search from there.',
            style: AppTextStyles.sans(fontSize: 13, color: AppColors.textSecondary)),
        const SizedBox(height: AppSpacing.lg),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final entry in kSeoulAreas.entries)
              InkWell(
                onTap: () => onPick(entry.value),
                borderRadius: BorderRadius.circular(20),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.lg, vertical: AppSpacing.smMd),
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    border: Border.all(color: AppColors.border),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(entry.key,
                      style: AppTextStyles.sans(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textPrimary)),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

/// E-Gen 이 통째로 죽었을 때 보여줄 최소 목록. 서울 권역 대형병원 5곳을
/// 지리적으로 흩어 골랐다 (성북·종로·서대문·서초·송파). 전화번호는 전부
/// 응급실 직통번호(dutyTel3)이고 좌표·주소는 getEgytBassInfoInqire 실응답에서
/// 가져왔다. 응급 화면은 어떤 경우에도 막다른 길이 되면 안 된다.
const _kErFallback = <EmergencyRoom>[
  EmergencyRoom(
      name: '연세대학교의과대학세브란스병원',
      address: '서울특별시 서대문구 연세로 50-1 (신촌동)',
      lat: 37.562117,
      lng: 126.940828,
      distanceKm: 0,
      erPhone: '02-2227-7777',
      beds: 0,
      bedsState: 'unknown',
      updatedAt: ''),
  EmergencyRoom(
      name: '서울대학교병원',
      address: '서울특별시 종로구 대학로 101 (연건동)',
      lat: 37.579666,
      lng: 126.998963,
      distanceKm: 0,
      erPhone: '02-2072-2475',
      beds: 0,
      bedsState: 'unknown',
      updatedAt: ''),
  EmergencyRoom(
      name: '고려대학교의과대학부속병원 (안암병원)',
      address: '서울특별시 성북구 고려대로 73 (안암동5가)',
      lat: 37.587156,
      lng: 127.026471,
      distanceKm: 0,
      erPhone: '02-920-5374',
      beds: 0,
      bedsState: 'unknown',
      updatedAt: ''),
  EmergencyRoom(
      name: '가톨릭대학교 서울성모병원',
      address: '서울특별시 서초구 반포대로 222 (반포동)',
      lat: 37.501801,
      lng: 127.004727,
      distanceKm: 0,
      erPhone: '02-2258-2370',
      beds: 0,
      bedsState: 'unknown',
      updatedAt: ''),
  EmergencyRoom(
      name: '서울아산병원',
      address: '서울특별시 송파구 올림픽로43길 88 (풍납동)',
      lat: 37.526564,
      lng: 127.108238,
      distanceKm: 0,
      erPhone: '02-3010-3333',
      beds: 0,
      bedsState: 'unknown',
      updatedAt: ''),
];

/// 응급실. API 가 죽어도 119 안내와 대형병원 5곳은 항상 보인다.
class _EmergencyView extends StatefulWidget {
  final LatLng at;
  const _EmergencyView(this.at);

  @override
  State<_EmergencyView> createState() => _EmergencyViewState();
}

class _EmergencyViewState extends State<_EmergencyView> {
  List<EmergencyRoom>? _rooms;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    LiveHelpService.fetchEmergencyRooms(widget.at).then((v) {
      // A successful-but-empty response (data.go.kr error envelope that
      // slipped past the server guard, a traveller outside Seoul, E-Gen
      // maintenance) is treated the same as a failure so the fallback list
      // renders instead of a blank area under the 119 banner.
      if (mounted) {
        setState(() {
          if (v.isEmpty) {
            _failed = true;
          } else {
            _rooms = v;
          }
        });
      }
    }).catchError((_) {
      if (mounted) setState(() => _failed = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final rooms = _rooms;
    return Column(
      children: [
        const _Call119Banner(),
        Expanded(
          child: _failed
              ? ListView(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  children: [
                    Text(
                      "Live hospital data is unavailable. These major ERs are open 24 hours — call ahead before you go.",
                      style: AppTextStyles.sans(
                          fontSize: 13, color: AppColors.textSecondary, height: 1.5),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    for (final r in _kErFallback) ...[
                      _RoomCard(r),
                      const SizedBox(height: AppSpacing.smMd),
                    ],
                  ],
                )
              : rooms == null
                  ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
                  : ListView.separated(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      itemCount: rooms.length,
                      separatorBuilder: (_, _) =>
                          const SizedBox(height: AppSpacing.smMd),
                      itemBuilder: (_, i) =>
                          _RoomCard(rooms[i], from: widget.at),
                    ),
        ),
      ],
    );
  }
}

class _Call119Banner extends StatelessWidget {
  const _Call119Banner();

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => _launch(context, Uri(scheme: 'tel', path: '119'), '119'),
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, 0),
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.accentTint,
          border: Border.all(color: AppColors.accent),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            const Icon(Icons.emergency_rounded, color: AppColors.accent),
            const SizedBox(width: AppSpacing.smMd),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Call 119',
                      style: AppTextStyles.sans(
                          fontSize: 15,
                          fontWeight: FontWeight.w800,
                          color: AppColors.accent)),
                  Text('Ambulance and interpreter, 24 hours',
                      style: AppTextStyles.sans(
                          fontSize: 12, color: AppColors.textPrimary)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// E-Gen 의 `hvidate` (`yyyyMMddHHmmss`, 예: `20260821182414`) 를 사람이 읽을
/// 수 있는 시각으로 바꾼다. 60초 캐시 + 요청 지연이 있으니 병상 수를 실시간처럼
/// 보여주지 않기 위한 최소 신선도 힌트다. 형식이 안 맞으면(폴백 목록은 항상
/// 빈 문자열) null 을 돌려주고 호출부가 렌더링을 건너뛴다.
String? _formatBedsUpdatedAt(String raw) {
  if (raw.length < 12) return null;
  final hh = raw.substring(8, 10);
  final mm = raw.substring(10, 12);
  return 'Updated $hh:$mm';
}

class _RoomCard extends StatelessWidget {
  final EmergencyRoom r;

  /// 길찾기 출발지. 폴백 목록은 사용자 위치를 모른 채 그려질 수 있어 null 을 허용하고,
  /// 그때는 도착지만 넘겨 카카오가 기기 현재 위치를 출발지로 쓰게 한다.
  final LatLng? from;

  const _RoomCard(this.r, {this.from});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(r.name,
                    style: AppTextStyles.sans(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary)),
              ),
              const SizedBox(width: AppSpacing.sm),
              // hvec 는 정원 초과를 음수로 쓴다. 만원일 때 숫자를 보여주지 않는다.
              // 폴백 목록은 bedsState 가 unknown 이라 뱃지를 아예 숨긴다.
              if (r.bedsState != 'unknown')
                _Pill(
                  text: r.isFull ? 'Full' : '${r.beds} beds',
                  fg: r.isFull ? AppColors.accent : AppColors.success,
                  bg: r.isFull ? AppColors.accentTint : AppColors.primaryTint,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
              r.distanceKm > 0
                  ? '${r.distanceKm.toStringAsFixed(1)} km · ${r.address}'
                  : r.address,
              style: AppTextStyles.sans(
                  fontSize: 12, color: AppColors.textSecondary, height: 1.4)),
          if (_formatBedsUpdatedAt(r.updatedAt) case final hint?) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(hint,
                style:
                    AppTextStyles.sans(fontSize: 11, color: AppColors.textSecondary)),
          ],
          const SizedBox(height: AppSpacing.smMd),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              if (r.erPhone.isNotEmpty)
                _MiniButton(
                  icon: Icons.call_rounded,
                  label: r.erPhone,
                  onTap: () => _launch(
                      context,
                      Uri(scheme: 'tel', path: r.erPhone.replaceAll('-', '')),
                      r.erPhone),
                ),
              _MiniButton(
                icon: Icons.directions_rounded,
                label: 'Directions',
                onTap: () => _launch(
                    context,
                    _routeTo(
                        from, LatLng(r.lat, r.lng), r.name, KakaoRouteMode.car),
                    r.address),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;
  final Color fg;
  final Color bg;
  const _Pill({required this.text, required this.fg, required this.bg});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.smMd, vertical: AppSpacing.xs),
      decoration:
          BoxDecoration(color: bg, borderRadius: BorderRadius.circular(20)),
      child: Text(text,
          style: AppTextStyles.sans(
              fontSize: 11, fontWeight: FontWeight.w800, color: fg)),
    );
  }
}

/// 주변 추천. 카페/음식점 토글 + 거리순 5개.
class _NearbyView extends StatefulWidget {
  final LatLng at;
  const _NearbyView(this.at);

  @override
  State<_NearbyView> createState() => _NearbyViewState();
}

class _NearbyViewState extends State<_NearbyView> {
  String _type = 'cafe';
  List<NearbyPlace>? _places;
  bool _failed = false;

  // Bumped on every _load() call and captured per-request. A response for a
  // stale generation (e.g. the "cafe" request resolving after a later
  // "restaurant" tap) is discarded instead of overwriting fresher results.
  int _gen = 0;

  final _scrollCtrl = ScrollController();

  /// 마커 탭 → 해당 카드로 스크롤하기 위한 카드별 키. 매 로드마다 갈아끼운다.
  List<GlobalKey> _cardKeys = const [];

  @override
  void initState() {
    super.initState();
    _load(_type);
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _revealCard(int i) {
    if (i >= _cardKeys.length) return;
    final ctx = _cardKeys[i].currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(ctx,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
        alignment: 0.1);
  }

  void _load(String type) {
    final gen = ++_gen;
    setState(() {
      _type = type;
      _places = null;
      _failed = false;
    });
    LiveHelpService.fetchNearby(widget.at, type).then((v) {
      if (mounted && gen == _gen) {
        setState(() {
          _places = v;
          _cardKeys = List.generate(v.length, (_) => GlobalKey());
        });
      }
    }).catchError((_) {
      if (mounted && gen == _gen) setState(() => _failed = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final places = _places;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
              for (final t in const ['cafe', 'restaurant'])
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: InkWell(
                    onTap: () {
                      if (_type == t) return;
                      _load(t);
                    },
                    borderRadius: BorderRadius.circular(20),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
                      decoration: BoxDecoration(
                        color: _type == t ? AppColors.primaryTint : AppColors.surface,
                        border:
                            Border.all(color: _type == t ? AppColors.primary : AppColors.border),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(t == 'cafe' ? 'Cafes' : 'Restaurants',
                          style: AppTextStyles.sans(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w700,
                              color: _type == t ? AppColors.primary : AppColors.textSecondary)),
                    ),
                  ),
                ),
            ],
          ),
        ),
        if (places != null && places.isNotEmpty)
          _NearbyMap(
            me: widget.at,
            pins: [
              for (final p in places)
                (at: LatLng(p.lat, p.lng), color: AppColors.textPrimary, fg: AppColors.surface),
            ],
            onMarkerTap: _revealCard,
          ),
        Expanded(
          child: _failed
              ? Center(
                  child: Text("Couldn't load nearby places right now.",
                      style: AppTextStyles.sans(
                          fontSize: 13, color: AppColors.textSecondary)),
                )
              : places == null
                  ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
                  : places.isEmpty
                      ? Center(
                          child: Text('Nothing within walking distance here.',
                              style: AppTextStyles.sans(
                                  fontSize: 13, color: AppColors.textSecondary)),
                        )
                      : ListView.separated(
                          controller: _scrollCtrl,
                          padding: const EdgeInsets.fromLTRB(
                              AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, AppSpacing.xxl),
                          itemCount: places.length,
                          separatorBuilder: (_, _) =>
                              const SizedBox(height: AppSpacing.smMd),
                          itemBuilder: (_, i) => _PlaceCard(
                            places[i],
                            key: i < _cardKeys.length ? _cardKeys[i] : null,
                            index: i + 1,
                            from: widget.at,
                          ),
                        ),
        ),
      ],
    );
  }
}

class _PlaceCard extends StatelessWidget {
  final NearbyPlace p;
  final LatLng? from;

  /// 지도 마커와 대응시키는 1-기반 순번.
  final int index;

  const _PlaceCard(this.p, {super.key, required this.index, this.from});

  @override
  Widget build(BuildContext context) {
    final openNow = p.openNow;
    final rating = p.rating;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // 지도 마커와 같은 번호. 둘을 눈으로 잇는 유일한 단서라 항상 보인다.
              Container(
                width: 22,
                height: 22,
                margin: const EdgeInsets.only(right: AppSpacing.sm),
                decoration:
                    const BoxDecoration(color: AppColors.textPrimary, shape: BoxShape.circle),
                alignment: Alignment.center,
                child: Text('$index',
                    style: AppTextStyles.sans(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: AppColors.surface)),
              ),
              Expanded(
                child: Text(p.name,
                    style: AppTextStyles.sans(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary)),
              ),
              // 리뷰가 없는 업소는 구글이 평점을 주지 않는다 — 그럴 땐 뱃지를 숨긴다.
              if (rating != null)
                _Pill(
                    text: '$rating★ (${p.reviews})',
                    fg: AppColors.textPrimary,
                    bg: AppColors.warningTint),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text('${p.distanceM} m · ${p.address}',
              style: AppTextStyles.sans(
                  fontSize: 12, color: AppColors.textSecondary, height: 1.4)),
          // Places 결과 20건 중 19건에 사진이 있다. 없으면 자리를 접는다 —
          // 빈 회색 박스를 남기면 로딩이 멈춘 것처럼 보인다.
          if (p.photoRef.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.smMd),
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Image.network(
                LiveHelpService.placePhotoUrl(p.photoRef, width: 800),
                height: 132,
                width: double.infinity,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => const SizedBox.shrink(),
                loadingBuilder: (ctx, child, progress) => progress == null
                    ? child
                    : Container(
                        height: 132,
                        color: AppColors.background,
                        alignment: Alignment.center,
                        child: const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: AppColors.primary),
                        ),
                      ),
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.smMd),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              if (openNow != null)
                _Pill(
                  text: openNow ? 'Open now' : 'Closed',
                  fg: openNow ? AppColors.success : AppColors.textSecondary,
                  bg: openNow ? AppColors.primaryTint : AppColors.background,
                ),
              _MiniButton(
                icon: Icons.directions_walk_rounded,
                label: 'Directions',
                onTap: () => _launch(
                    context,
                    _routeTo(from, LatLng(p.lat, p.lng), p.name,
                        KakaoRouteMode.walk),
                    p.address),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 지도에 찍을 결과 하나. 색은 호출부가 정한다 — 주변 추천은 종류가 하나라
/// 단색이고, Explore 는 카테고리색으로 6가지가 섞인다.
typedef _Pin = ({LatLng at, Color color, Color fg});

/// 결과 목록 위의 작은 지도. 주변 추천과 Explore 가 같이 쓴다.
///
/// kakao_map_plugin 이 아니라 flutter_map(OSM)을 쓴다 — 카카오 플러그인은
/// ios/android 전용이라 브라우저 개발 루프가 깨지고, 이 화면은 타일만 있으면
/// 되지 카카오 SDK 기능이 필요하지 않다. 길찾기는 카카오로 넘긴다.
class _NearbyMap extends StatelessWidget {
  final LatLng me;
  final List<_Pin> pins;
  final ValueChanged<int> onMarkerTap;

  const _NearbyMap({
    required this.me,
    required this.pins,
    required this.onMarkerTap,
  });

  /// 내 위치와 결과가 모두 들어오도록 잡은 경계. 여유값은 작게 두지만,
  /// Explore 는 반경 제한이 없어 6km 짜리 결과가 섞일 수 있으므로 경계 자체는
  /// 넓게 잡히는 게 맞다 — 화면 밖 마커를 만드는 것보다 낫다.
  LatLngBounds get _bounds {
    var minLat = me.latitude, maxLat = me.latitude;
    var minLng = me.longitude, maxLng = me.longitude;
    for (final p in pins) {
      minLat = p.at.latitude < minLat ? p.at.latitude : minLat;
      maxLat = p.at.latitude > maxLat ? p.at.latitude : maxLat;
      minLng = p.at.longitude < minLng ? p.at.longitude : minLng;
      maxLng = p.at.longitude > maxLng ? p.at.longitude : maxLng;
    }
    const pad = 0.0012;
    return LatLngBounds(
      LatLng(minLat - pad, minLng - pad),
      LatLng(maxLat + pad, maxLng + pad),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 200,
      child: FlutterMap(
        options: MapOptions(
          initialCameraFit: CameraFit.bounds(
              bounds: _bounds, padding: const EdgeInsets.all(28)),
          interactionOptions: const InteractionOptions(
            flags: InteractiveFlag.pinchZoom | InteractiveFlag.drag,
          ),
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            userAgentPackageName: 'com.example.seoulfitFlutter',
          ),
          MarkerLayer(
            markers: [
              Marker(
                point: me,
                width: 22,
                height: 22,
                child: Container(
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.surface, width: 3),
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.textPrimary.withValues(alpha: 0.25),
                        blurRadius: 6,
                      ),
                    ],
                  ),
                ),
              ),
              for (var i = 0; i < pins.length; i++)
                Marker(
                  point: pins[i].at,
                  width: 30,
                  height: 30,
                  child: GestureDetector(
                    onTap: () => onMarkerTap(i),
                    child: Container(
                      decoration: BoxDecoration(
                        color: pins[i].color,
                        shape: BoxShape.circle,
                        border: Border.all(color: AppColors.surface, width: 2),
                      ),
                      alignment: Alignment.center,
                      child: Text('${i + 1}',
                          style: AppTextStyles.sans(
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                              color: pins[i].fg)),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 주변 관광 POI. 카테고리 칩(단일선택) + 거리순 상위 20건.
///
/// 카페/음식점을 다루는 [_NearbyView] 와 달리 반경으로 자르지 않는다 — POI
/// 밀도가 지역마다 10배 넘게 차이나서(종로 1km 71건 vs 여의도 6건) 반경을
/// 고정하면 어떤 지역에서는 빈 화면이 된다. 대신 거리를 정직하게 표기한다.
class _ExploreView extends StatefulWidget {
  final LatLng at;
  const _ExploreView(this.at);

  @override
  State<_ExploreView> createState() => _ExploreViewState();
}

class _ExploreViewState extends State<_ExploreView> {
  /// null 이면 전체. 단일선택이라 스칼라 하나로 충분하다.
  String? _category;

  List<TourPoi>? _pois;
  bool _failed = false;

  /// [_NearbyViewState] 와 같은 이유의 세대 카운터. 칩을 빠르게 연타하면
  /// 먼저 보낸 요청이 나중에 도착할 수 있어, 최신 요청의 응답만 반영한다.
  int _gen = 0;

  final _scrollCtrl = ScrollController();
  List<GlobalKey> _cardKeys = const [];

  @override
  void initState() {
    super.initState();
    _load(null);
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _revealCard(int i) {
    if (i >= _cardKeys.length) return;
    final ctx = _cardKeys[i].currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(ctx,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
        alignment: 0.1);
  }

  void _load(String? category) {
    final gen = ++_gen;
    setState(() {
      _category = category;
      _pois = null;
      _failed = false;
    });
    LiveHelpService.fetchTourPois(widget.at, category: category).then((v) {
      if (mounted && gen == _gen) {
        setState(() {
          _pois = v;
          _cardKeys = List.generate(v.length, (_) => GlobalKey());
        });
      }
    }).catchError((_) {
      if (mounted && gen == _gen) setState(() => _failed = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final pois = _pois;
    return Column(
      children: [
        SizedBox(
          height: 56,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            children: [
              for (final (code, label) in _kTourCategories)
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: _TourChip(
                    label: label,
                    // All 은 특정 카테고리색이 없으므로 브랜드 액센트를 쓴다.
                    accent: code == null ? AppColors.primary : categoryColor(code),
                    selected: _category == code,
                    onTap: () {
                      if (_category == code) return;
                      _load(code);
                    },
                  ),
                ),
            ],
          ),
        ),
        if (pois != null && pois.isNotEmpty)
          _NearbyMap(
            me: widget.at,
            pins: [
              for (final p in pois)
                (
                  at: LatLng(p.lat, p.lng),
                  color: categoryColor(p.category),
                  fg: categoryFg(p.category),
                ),
            ],
            onMarkerTap: _revealCard,
          ),
        Expanded(
          child: _failed
              ? Center(
                  child: Text("Couldn't load places right now.",
                      style: AppTextStyles.sans(
                          fontSize: 13, color: AppColors.textSecondary)),
                )
              : pois == null
                  ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
                  : pois.isEmpty
                      ? Center(
                          child: Text('Nothing in this category nearby.',
                              style: AppTextStyles.sans(
                                  fontSize: 13, color: AppColors.textSecondary)),
                        )
                      : ListView.separated(
                          controller: _scrollCtrl,
                          padding: const EdgeInsets.fromLTRB(
                              AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, AppSpacing.xxl),
                          itemCount: pois.length,
                          separatorBuilder: (_, _) =>
                              const SizedBox(height: AppSpacing.smMd),
                          itemBuilder: (_, i) => _TourPoiCard(
                            pois[i],
                            key: i < _cardKeys.length ? _cardKeys[i] : null,
                            index: i + 1,
                            from: widget.at,
                          ),
                        ),
        ),
      ],
    );
  }
}

/// 카테고리 칩. 선택 시 그 카테고리색으로 물든다 — 지도 마커와 같은 색이라
/// 무엇을 보고 있는지 칩만 봐도 안다.
class _TourChip extends StatelessWidget {
  final String label;
  final Color accent;
  final bool selected;
  final VoidCallback onTap;

  const _TourChip({
    required this.label,
    required this.accent,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: AnimatedContainer(
        duration: Motion.fast,
        curve: Motion.enter,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        decoration: BoxDecoration(
          color: accent.withValues(alpha: selected ? 0.16 : 0.07),
          border: Border.all(color: accent, width: selected ? 1.5 : 1),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(label,
            style: AppTextStyles.sans(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: accent)),
      ),
    );
  }
}

/// 목록의 POI 한 장. 탭하면 설명·사진이 든 상세 시트가 올라온다.
class _TourPoiCard extends StatelessWidget {
  final TourPoi p;
  final LatLng? from;

  /// 지도 마커와 대응시키는 1-기반 순번.
  final int index;

  const _TourPoiCard(this.p, {super.key, required this.index, this.from});

  @override
  Widget build(BuildContext context) {
    final color = categoryColor(p.category);
    return PressableScale(
      onTap: () => _showTourPoiSheet(context, p, from),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.smMd),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          children: [
            // 지도 마커와 같은 번호·같은 색. 둘을 눈으로 잇는 단서다.
            Container(
              width: 22,
              height: 22,
              margin: const EdgeInsets.only(right: AppSpacing.sm),
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              alignment: Alignment.center,
              child: Text('$index',
                  style: AppTextStyles.sans(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: categoryFg(p.category))),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.sans(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary)),
                  const SizedBox(height: 2),
                  Text('${p.distanceLabel} · ${p.address}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.sans(
                          fontSize: 12, color: AppColors.textSecondary)),
                ],
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            _TourThumb(p, size: 56),
          ],
        ),
      ),
    );
  }
}

/// 431건 중 118건은 사진이 없다. 그럴 때 회색 박스 대신 카테고리색을 옅게 깐
/// 아이콘을 둔다 — 빈자리가 아니라 의도된 자리로 보이게.
class _TourThumb extends StatelessWidget {
  final TourPoi p;
  final double size;

  const _TourThumb(this.p, {required this.size});

  static const _radius = 10.0;

  static const _icons = <String, IconData>{
    'VE': Icons.museum_outlined,
    'EX': Icons.local_activity_outlined,
    'HS': Icons.account_balance_outlined,
    'NA': Icons.park_outlined,
    'LS': Icons.directions_bike_outlined,
    'AC': Icons.hotel_outlined,
  };

  Widget _placeholder() {
    final color = categoryColor(p.category);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(_radius),
      ),
      child: Icon(_icons[p.category] ?? Icons.place_outlined,
          color: color, size: size * 0.4),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (p.image.isEmpty) return _placeholder();
    return ClipRRect(
      borderRadius: BorderRadius.circular(_radius),
      child: Image.network(
        p.image,
        width: size,
        height: size,
        fit: BoxFit.cover,
        // visitkorea 이미지가 종종 404 로 사라진다. 폴백이 없으면 카드가 깨진다.
        errorBuilder: (_, _, _) => _placeholder(),
      ),
    );
  }
}

/// POI 상세 시트. 설명이 평균 600자라 카드에 넣을 수 없어 여기서만 펼친다.
/// 결측 필드는 줄을 통째로 숨긴다 — 빈 라벨을 남기면 데이터가 없는 건지
/// 앱이 못 읽은 건지 알 수 없다.
void _showTourPoiSheet(BuildContext context, TourPoi p, LatLng? from) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) => DraggableScrollableSheet(
      initialChildSize: 0.75,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      expand: false,
      builder: (_, controller) =>
          _TourPoiSheet(p, from: from, controller: controller),
    ),
  );
}

class _TourPoiSheet extends StatelessWidget {
  final TourPoi p;
  final LatLng? from;
  final ScrollController controller;

  const _TourPoiSheet(this.p, {required this.from, required this.controller});

  @override
  Widget build(BuildContext context) {
    final color = categoryColor(p.category);
    final label = _kTourCategories
        .firstWhere((c) => c.$1 == p.category, orElse: () => (null, 'Place'))
        .$2;
    return ListView(
      controller: controller,
      padding: EdgeInsets.zero,
      children: [
        if (p.image.isNotEmpty)
          ClipRRect(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
            child: Image.network(
              p.image,
              height: 200,
              width: double.infinity,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => const SizedBox.shrink(),
            ),
          ),
        Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  _Pill(
                      text: label,
                      fg: color,
                      bg: color.withValues(alpha: 0.12)),
                  const SizedBox(width: AppSpacing.sm),
                  Text(p.distanceLabel,
                      style: AppTextStyles.sans(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textSecondary)),
                ],
              ),
              const SizedBox(height: AppSpacing.smMd),
              Text(p.name,
                  style: AppTextStyles.sans(
                      fontSize: 20,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                      height: 1.25)),
              const SizedBox(height: AppSpacing.xs),
              Text(p.address,
                  style: AppTextStyles.sans(
                      fontSize: 12.5, color: AppColors.textSecondary, height: 1.4)),
              if (p.overview.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                Text(p.overview,
                    style: AppTextStyles.sans(
                        fontSize: 13.5, color: AppColors.textPrimary, height: 1.6)),
              ],
              const SizedBox(height: AppSpacing.lg),
              _InfoRow(Icons.schedule_rounded, p.hours),
              _InfoRow(Icons.event_busy_rounded, p.closed),
              _InfoRow(Icons.confirmation_number_outlined, p.fee),
              _InfoRow(Icons.local_parking_rounded, p.parking),
              const SizedBox(height: AppSpacing.smMd),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  _MiniButton(
                    icon: Icons.directions_walk_rounded,
                    label: 'Directions',
                    onTap: () => _launch(
                        context,
                        _routeTo(from, LatLng(p.lat, p.lng), p.name,
                            KakaoRouteMode.walk),
                        p.address),
                  ),
                  if (p.tel.isNotEmpty)
                    _MiniButton(
                      icon: Icons.call_rounded,
                      label: 'Call',
                      onTap: () => _launch(
                          context, Uri(scheme: 'tel', path: p.tel), p.tel),
                    ),
                  if (p.homepage.isNotEmpty)
                    _MiniButton(
                      icon: Icons.language_rounded,
                      label: 'Website',
                      onTap: () =>
                          _launch(context, Uri.parse(p.homepage), p.homepage),
                    ),
                ],
              ),
              const DataSourceNote(),
            ],
          ),
        ),
      ],
    );
  }
}

/// 값이 있을 때만 보이는 정보 한 줄.
class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String value;
  const _InfoRow(this.icon, this.value);

  @override
  Widget build(BuildContext context) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(value,
                style: AppTextStyles.sans(
                    fontSize: 12.5, color: AppColors.textPrimary, height: 1.45)),
          ),
        ],
      ),
    );
  }
}

/// 칩 순서. null 은 'All'. 백엔드가 SP/TM/MO/DS/DF/SW 를 그대로 받는다.
/// 개수가 많은 것부터 둔다 — 첫 칩부터 빈 화면이면 필터가 고장 난 것처럼 보인다.
const _kShoppingCategories = <(String?, String)>[
  (null, 'All'),
  ('SP', 'Shops'),
  ('TM', 'Markets'),
  ('MO', 'Malls'),
  ('DS', 'Dept stores'),
  ('DF', 'Duty free'),
  ('SW', 'Supermarkets'),
];

/// 주변 쇼핑 POI. [_ExploreView] 와 같은 골격이고 데이터 출처만 다르다
/// (한국관광공사 대신 서울관광재단). 반경으로 자르지 않는 이유도 같다.
///
/// 면세점(DF) 5건, 대형마트(SW) 3건처럼 얇은 칩이 있다. 서울 전역에서 그만큼
/// 뿐이라 몇 km 떨어진 결과가 나오는데, 거리 표기가 정직하므로 감춰지지 않는다.
class _ShoppingView extends StatefulWidget {
  final LatLng at;
  const _ShoppingView(this.at);

  @override
  State<_ShoppingView> createState() => _ShoppingViewState();
}

class _ShoppingViewState extends State<_ShoppingView> {
  String? _category;
  List<ShoppingPoi>? _pois;
  bool _failed = false;

  /// [_ExploreViewState] 와 같은 세대 카운터. 칩을 연타하면 먼저 보낸 요청이
  /// 나중에 도착할 수 있어, 최신 요청의 응답만 반영한다.
  int _gen = 0;

  final _scrollCtrl = ScrollController();
  List<GlobalKey> _cardKeys = const [];

  @override
  void initState() {
    super.initState();
    _load(null);
  }

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _revealCard(int i) {
    if (i >= _cardKeys.length) return;
    final ctx = _cardKeys[i].currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(ctx,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
        alignment: 0.1);
  }

  void _load(String? category) {
    final gen = ++_gen;
    setState(() {
      _category = category;
      _pois = null;
      _failed = false;
    });
    LiveHelpService.fetchShoppingPois(widget.at, category: category).then((v) {
      if (mounted && gen == _gen) {
        setState(() {
          _pois = v;
          _cardKeys = List.generate(v.length, (_) => GlobalKey());
        });
      }
    }).catchError((_) {
      if (mounted && gen == _gen) setState(() => _failed = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final pois = _pois;
    return Column(
      children: [
        SizedBox(
          height: 56,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            children: [
              for (final (code, label) in _kShoppingCategories)
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: _TourChip(
                    label: label,
                    accent: code == null ? AppColors.primary : shoppingColor(code),
                    selected: _category == code,
                    onTap: () {
                      if (_category == code) return;
                      _load(code);
                    },
                  ),
                ),
            ],
          ),
        ),
        if (pois != null && pois.isNotEmpty)
          _NearbyMap(
            me: widget.at,
            pins: [
              for (final p in pois)
                (
                  at: LatLng(p.lat, p.lng),
                  color: shoppingColor(p.category),
                  fg: Colors.white,
                ),
            ],
            onMarkerTap: _revealCard,
          ),
        Expanded(
          child: _failed
              ? Center(
                  child: Text("Couldn't load shops right now.",
                      style: AppTextStyles.sans(
                          fontSize: 13, color: AppColors.textSecondary)),
                )
              : pois == null
                  ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
                  : pois.isEmpty
                      ? Center(
                          child: Text('Nothing in this category nearby.',
                              style: AppTextStyles.sans(
                                  fontSize: 13, color: AppColors.textSecondary)),
                        )
                      : ListView.separated(
                          controller: _scrollCtrl,
                          padding: const EdgeInsets.fromLTRB(
                              AppSpacing.lg, AppSpacing.smMd, AppSpacing.lg, AppSpacing.xxl),
                          itemCount: pois.length,
                          separatorBuilder: (_, _) =>
                              const SizedBox(height: AppSpacing.smMd),
                          itemBuilder: (_, i) => _ShoppingCard(
                            pois[i],
                            key: i < _cardKeys.length ? _cardKeys[i] : null,
                            index: i + 1,
                            from: widget.at,
                          ),
                        ),
        ),
      ],
    );
  }
}

class _ShoppingCard extends StatelessWidget {
  final ShoppingPoi p;
  final LatLng? from;
  final int index;

  const _ShoppingCard(this.p, {super.key, required this.index, this.from});

  @override
  Widget build(BuildContext context) {
    final color = shoppingColor(p.category);
    return PressableScale(
      onTap: () => _showShoppingSheet(context, p, from),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.smMd),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 22,
              height: 22,
              margin: const EdgeInsets.only(right: AppSpacing.sm),
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              alignment: Alignment.center,
              child: Text('$index',
                  style: AppTextStyles.sans(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: Colors.white)),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.sans(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary)),
                  const SizedBox(height: 2),
                  Text(
                      '${p.distanceLabel} · ${kShoppingNames[p.category] ?? ""}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.sans(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: color)),
                  if (p.summary.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(p.summary,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTextStyles.sans(
                            fontSize: 12, height: 1.35, color: AppColors.textSecondary)),
                  ],
                ],
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            _ShoppingThumb(p, size: 56),
          ],
        ),
      ),
    );
  }
}

class _ShoppingThumb extends StatelessWidget {
  final ShoppingPoi p;
  final double size;

  const _ShoppingThumb(this.p, {required this.size});

  static const _icons = <String, IconData>{
    'SP': Icons.storefront_outlined,
    'TM': Icons.storefront_rounded,
    'MO': Icons.local_mall_outlined,
    'DS': Icons.apartment_rounded,
    'DF': Icons.flight_takeoff_rounded,
    'SW': Icons.shopping_cart_outlined,
  };

  @override
  Widget build(BuildContext context) {
    final color = shoppingColor(p.category);
    final fallback = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(_icons[p.category] ?? Icons.storefront_outlined,
          size: size * 0.42, color: color),
    );
    if (p.image.isEmpty) return fallback;
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Image.network(p.image,
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) => fallback),
    );
  }
}

void _showShoppingSheet(BuildContext context, ShoppingPoi p, LatLng? from) {
  final color = shoppingColor(p.category);
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => DraggableScrollableSheet(
      initialChildSize: 0.65,
      minChildSize: 0.35,
      maxChildSize: 0.92,
      expand: false,
      // _TourPoiSheet 과 같은 구성이다 — 사진이 시트 맨 위를 꽉 채우고 위쪽
      // 모서리만 둥글다. 그래서 ListView 는 padding 을 0 으로 두고 본문만
      // 따로 감싼다.
      builder: (_, controller) => ListView(
        controller: controller,
        padding: EdgeInsets.zero,
        children: [
          if (p.image.isNotEmpty)
            ClipRRect(
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(20)),
              child: Image.network(
                p.image,
                height: 200,
                width: double.infinity,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => const SizedBox.shrink(),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg, AppSpacing.lg, AppSpacing.lg, AppSpacing.xxl),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(kShoppingNames[p.category] ?? '',
                    style: AppTextStyles.sans(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w800,
                        color: color)),
                const SizedBox(height: 2),
                Text(p.title,
                    style: AppTextStyles.sans(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.textPrimary)),
                const SizedBox(height: 4),
                Text('${p.distanceLabel} · ${p.address}',
                    style: AppTextStyles.sans(
                        fontSize: 12.5, color: AppColors.textSecondary)),
                const SizedBox(height: AppSpacing.smMd),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [
                    _MiniButton(
                      icon: Icons.directions_walk_rounded,
                      label: 'Directions',
                      onTap: () => _launch(
                          context,
                          _routeTo(from, LatLng(p.lat, p.lng), p.title,
                              KakaoRouteMode.walk),
                          p.address),
                    ),
                    if (p.tel.isNotEmpty)
                      _MiniButton(
                        icon: Icons.call_rounded,
                        label: 'Call',
                        onTap: () => _launch(
                            context, Uri(scheme: 'tel', path: p.tel), p.tel),
                      ),
                    if (p.homepage.isNotEmpty)
                      _MiniButton(
                        icon: Icons.language_rounded,
                        label: 'Website',
                        onTap: () =>
                            _launch(context, Uri.parse(p.homepage), p.homepage),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.lg),
                // _InfoRow 는 값이 비면 스스로 사라진다. 영업시간 285/310,
                // 지하철 308/310 이라 결측이 흔하다.
                _InfoRow(Icons.schedule_rounded, p.hours),
                _InfoRow(Icons.subway_rounded, p.subway),
                if (p.overview.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.smMd),
                  Text(p.overview,
                      style: AppTextStyles.sans(
                          fontSize: 13, height: 1.55, color: AppColors.textPrimary)),
                ],
                const DataSourceNote(source: DataSource.seoulTourism),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
