import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/trip_checkin.dart';
import '../../providers/trip_provider.dart';
import '../../services/checkin_store.dart';
import '../../theme/theme.dart';
import '../../widgets/visited_route_map.dart';

/// The recap as a 9:16 card, sized for an Instagram story.
///
/// There is no image export: the card is laid out at story proportions so the
/// traveller can screenshot it, which is the whole feature. Building a
/// renderer would be the single largest item in this feature for no gain the
/// screenshot does not already deliver.
class TripStoryScreen extends StatefulWidget {
  const TripStoryScreen({super.key});

  @override
  State<TripStoryScreen> createState() => _TripStoryScreenState();
}

class _TripStoryScreenState extends State<TripStoryScreen> {
  TripCheckin? _trip;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // TripProvider mints the id on the first check-in of a trip; falling
    // back to the store's own last-saved id is what lets a restarted app
    // still find yesterday's record.
    final tripId = context.read<TripProvider>().tripId;
    var trip = tripId == null ? null : await CheckinStore.load(tripId);
    trip ??= await CheckinStore.loadActive();
    if (!mounted) return;
    setState(() {
      _trip = trip;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(
        backgroundColor: AppColors.textPrimary,
        body: Center(child: CircularProgressIndicator(color: AppColors.primary)),
      );
    }
    final trip = _trip;
    final pointsByDay = {
      if (trip != null)
        for (final day in trip.plannedDays)
          if (trip.visitedPointsFor(day).isNotEmpty)
            day: trip.visitedPointsFor(day),
    };

    return Scaffold(
      backgroundColor: AppColors.textPrimary,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: IconButton(
                icon: const Icon(Icons.close_rounded, color: Colors.white),
                onPressed: () => Navigator.pop(context),
              ),
            ),
            Expanded(
              child: Center(
                child: pointsByDay.isEmpty
                    ? Text('지도에 그릴 기록이 아직 없어요',
                        style: AppTextStyles.sans(
                            fontSize: 14, color: Colors.white70))
                    : Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 20),
                        child: AspectRatio(
                          aspectRatio: 9 / 16,
                          child: _StoryCard(
                            trip: trip!,
                            pointsByDay: pointsByDay,
                          ),
                        ),
                      ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 16, top: 8),
              child: Text('스크린샷해서 스토리에 올려보세요',
                  style: AppTextStyles.sans(
                      fontSize: 12, color: Colors.white54)),
            ),
          ],
        ),
      ),
    );
  }
}

class _StoryCard extends StatelessWidget {
  final TripCheckin trip;
  final Map<int, List<VisitedPoint>> pointsByDay;

  const _StoryCard({required this.trip, required this.pointsByDay});

  /// "종로 · 성북을 걸었어요" — the districts carry the personal note that makes
  /// the card worth posting. Districts are stored without their 구 suffix here
  /// because "종로 · 성북" reads better than "종로구 · 성북구". Falls back to a
  /// plain city line when no address carried a district.
  String get _title {
    if (trip.areas.isEmpty) return '서울을 걸었어요';
    final names = trip.areas
        .map((a) => a.endsWith('구') ? a.substring(0, a.length - 1) : a)
        .toList()
      ..sort();
    final shown = names.take(3).join(' · ');
    return '$shown을 걸었어요';
  }

  int get _visitedCount =>
      pointsByDay.values.fold(0, (sum, points) => sum + points.length);

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final date = '${today.year}.${today.month.toString().padLeft(2, '0')}.'
        '${today.day.toString().padLeft(2, '0')}';

    return Container(
      decoration: BoxDecoration(
        color: AppColors.background,
        borderRadius: BorderRadius.circular(20),
      ),
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('SEOUL · $date',
              style: AppTextStyles.sans(
                fontSize: 11,
                fontWeight: FontWeight.w800,
                letterSpacing: 1.6,
                color: AppColors.textSecondary,
              )),
          const SizedBox(height: 14),
          // The trace is the hero: it is the one image that says "this is the
          // shape of my trip" without needing a caption.
          Expanded(
            child: VisitedRouteMap(
              pointsByDay: pointsByDay,
              height: double.infinity,
              showTiles: false,
              showLabels: false,
            ),
          ),
          const SizedBox(height: 16),
          Text(_title,
              style: AppTextStyles.sans(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
                height: 1.3,
              )),
          const SizedBox(height: 6),
          Text('$_visitedCount곳 · ${trip.checkedDays.length}일',
              style: AppTextStyles.sans(
                  fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textSecondary)),
          const SizedBox(height: 10),
          Row(
            children: [
              Container(
                width: 18,
                height: 18,
                decoration: const BoxDecoration(
                    color: AppColors.primary, shape: BoxShape.circle),
              ),
              const SizedBox(width: 6),
              Text('SeoulFit',
                  style: AppTextStyles.sans(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary)),
            ],
          ),
        ],
      ),
    );
  }
}
