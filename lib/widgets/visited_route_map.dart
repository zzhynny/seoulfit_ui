import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../models/trip_checkin.dart';
import '../theme/theme.dart';

/// The stops a traveller actually visited, connected in visit order.
///
/// Deliberately draws only what was visited — the recap is not a list of what
/// someone failed to reach. Days are coloured from [kDayColors], the same
/// palette the planning map uses, so a day keeps its colour across screens.
///
/// [showTiles] is the whole difference between the two places this appears:
/// the recap shows the route over a real map so the traveller can see where
/// they were, while the share card drops the tiles and keeps just the trace on
/// a flat ground, which reads as a designed graphic rather than a screenshot.
class VisitedRouteMap extends StatelessWidget {
  /// Day number → the visited stops for that day, already in visit order.
  final Map<int, List<VisitedPoint>> pointsByDay;
  final double height;
  final bool showTiles;
  final bool showLabels;

  const VisitedRouteMap({
    super.key,
    required this.pointsByDay,
    this.height = 260,
    this.showTiles = true,
    this.showLabels = true,
  });

  /// Days that actually have something to draw, in ascending order. A day the
  /// traveller recorded but visited nothing on contributes no pins, so it is
  /// absent here while still counting as recorded everywhere else.
  List<int> get _days {
    final days = pointsByDay.keys
        .where((d) => (pointsByDay[d] ?? const []).isNotEmpty)
        .toList()
      ..sort();
    return days;
  }

  Color _colorFor(int index) => kDayColors[index % kDayColors.length];

  List<LatLng> _allPoints() => [
        for (final day in _days)
          for (final p in pointsByDay[day]!) LatLng(p.lat, p.lng),
      ];

  @override
  Widget build(BuildContext context) {
    final all = _allPoints();
    if (all.isEmpty) return const SizedBox.shrink();

    final days = _days;
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: SizedBox(
        height: height,
        child: FlutterMap(
          options: _options(all),
          children: [
            if (showTiles)
              TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.seoulfit.app',
                maxZoom: 19,
              ),
            PolylineLayer(
              polylines: [
                for (var i = 0; i < days.length; i++)
                  if (pointsByDay[days[i]]!.length >= 2)
                    Polyline(
                      points: [
                        for (final p in pointsByDay[days[i]]!)
                          LatLng(p.lat, p.lng),
                      ],
                      strokeWidth: showTiles ? 3.5 : 5,
                      color: _colorFor(i),
                    ),
              ],
            ),
            MarkerLayer(
              markers: [
                for (var i = 0; i < days.length; i++)
                  for (var n = 0; n < pointsByDay[days[i]]!.length; n++)
                    Marker(
                      width: showLabels ? 120 : 32,
                      height: 32,
                      point: LatLng(
                        pointsByDay[days[i]]![n].lat,
                        pointsByDay[days[i]]![n].lng,
                      ),
                      alignment: Alignment.center,
                      child: _VisitPin(
                        number: n + 1,
                        color: _colorFor(i),
                        label: showLabels
                            ? pointsByDay[days[i]]![n].name
                            : null,
                      ),
                    ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// A share card is a still image, so its map must not respond to gestures —
  /// a viewer panning it out of frame before screenshotting would be a bug.
  MapOptions _options(List<LatLng> all) {
    final interaction = InteractionOptions(
      flags: showTiles ? InteractiveFlag.all : InteractiveFlag.none,
    );
    if (all.length == 1) {
      return MapOptions(
        initialCenter: all.first,
        initialZoom: 15,
        minZoom: 3,
        maxZoom: 18,
        interactionOptions: interaction,
      );
    }
    final lats = all.map((p) => p.latitude);
    final lngs = all.map((p) => p.longitude);
    return MapOptions(
      minZoom: 3,
      maxZoom: 18,
      interactionOptions: interaction,
      initialCameraFit: CameraFit.bounds(
        bounds: LatLngBounds(
          LatLng(lats.reduce((a, b) => a < b ? a : b),
              lngs.reduce((a, b) => a < b ? a : b)),
          LatLng(lats.reduce((a, b) => a > b ? a : b),
              lngs.reduce((a, b) => a > b ? a : b)),
        ),
        // Generous padding so pins near the edge keep their labels on screen.
        padding: const EdgeInsets.all(48),
      ),
    );
  }
}

class _VisitPin extends StatelessWidget {
  final int number;
  final Color color;
  final String? label;

  const _VisitPin({required this.number, required this.color, this.label});

  @override
  Widget build(BuildContext context) {
    final dot = Container(
      width: 26,
      height: 26,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 2),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.18),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      alignment: Alignment.center,
      child: Text(
        '$number',
        style: AppTextStyles.sans(
          fontSize: 12,
          fontWeight: FontWeight.w800,
          color: Colors.white,
        ),
      ),
    );
    final name = label;
    if (name == null) return Center(child: dot);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        dot,
        const SizedBox(width: 4),
        Flexible(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: AppColors.surface.withValues(alpha: 0.92),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTextStyles.sans(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
          ),
        ),
      ],
    );
  }
}
