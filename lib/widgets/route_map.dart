import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../models/trip.dart';
import '../theme/theme.dart';

/// The trip's stops drawn on a real map: one polyline and one run of numbered
/// markers per day, coloured from [kDayColors].
///
/// Falls back to the Figma route illustration when no stop has coordinates —
/// which is every stop under `--dart-define=USE_MOCKS=true`, since the mock
/// itinerary is display copy with no geography behind it.
class RouteMap extends StatelessWidget {
  const RouteMap({super.key, required this.itinerary, this.height = 200});

  final Itinerary itinerary;
  final double height;

  @override
  Widget build(BuildContext context) {
    final days = mappableDays(itinerary);
    final allPoints = [
      for (final day in days)
        for (final stop in day) stop.point,
    ];

    if (allPoints.isEmpty) return _FigmaRoutePlaceholder(height: height);

    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        height: height,
        child: Stack(
          fit: StackFit.expand,
          children: [
            // Behind the tiles: OSM tiles arrive over the network, and until
            // the first one paints FlutterMap renders an empty box that reads
            // as a broken image. The map covers this as soon as it has
            // anything to draw.
            Container(
              color: AppColors.surfaceMuted,
              alignment: Alignment.center,
              child: Text(
                'Loading map…',
                style: AppTextStyles.caption
                    .copyWith(color: AppColors.textSecondary),
              ),
            ),
            FlutterMap(
          options: _options(allPoints),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.seoulfit.app',
              maxZoom: 19,
            ),
            PolylineLayer(
              polylines: [
                for (var i = 0; i < days.length; i++)
                  if (days[i].length >= 2)
                    Polyline(
                      points: [for (final stop in days[i]) stop.point],
                      strokeWidth: 3.5,
                      color: kDayColors[i % kDayColors.length],
                    ),
              ],
            ),
            MarkerLayer(
              markers: [
                for (var i = 0; i < days.length; i++)
                  for (final stop in days[i])
                    Marker(
                      width: 28,
                      height: 28,
                      point: stop.point,
                      alignment: Alignment.center,
                      child: _NumberedMarker(
                        number: stop.order,
                        color: kDayColors[i % kDayColors.length],
                      ),
                    ),
              ],
            ),
          ],
            ),
          ],
        ),
      ),
    );
  }

  MapOptions _options(List<LatLng> points) {
    // A single stop has no extent to fit, and CameraFit.bounds on a
    // zero-area box zooms to maxZoom on one building.
    if (points.length == 1) {
      return MapOptions(
        initialCenter: points.first,
        initialZoom: 14,
        minZoom: 3,
        maxZoom: 18,
        interactionOptions: _interaction,
      );
    }

    final lats = points.map((p) => p.latitude);
    final lngs = points.map((p) => p.longitude);
    return MapOptions(
      minZoom: 3,
      maxZoom: 18,
      interactionOptions: _interaction,
      initialCameraFit: CameraFit.bounds(
        bounds: LatLngBounds(
          LatLng(lats.reduce((a, b) => a < b ? a : b),
              lngs.reduce((a, b) => a < b ? a : b)),
          LatLng(lats.reduce((a, b) => a > b ? a : b),
              lngs.reduce((a, b) => a > b ? a : b)),
        ),
        padding: const EdgeInsets.all(32),
      ),
    );
  }

  /// Pan and pinch only. The map sits inside a scrolling list, so leaving
  /// one-finger drag on the map would fight the list for the same gesture.
  static const _interaction = InteractionOptions(
    flags: InteractiveFlag.pinchZoom | InteractiveFlag.drag,
  );
}

/// One plottable stop: its number in the printed route list, and where it is.
@visibleForTesting
class MappedStop {
  const MappedStop(this.order, this.point);
  final int order;
  final LatLng point;
}

/// Stops that can actually be plotted, grouped by day and numbered
/// continuously across the trip so the marker numbers line up with the route
/// list printed under the map.
@visibleForTesting
List<List<MappedStop>> mappableDays(Itinerary itinerary) {
  final days = <List<MappedStop>>[];
  var order = 1;

  for (final day in itinerary.days) {
    final stops = <MappedStop>[];
    for (final activity in day.activities) {
      if (!activity.included) continue;
      final lat = activity.lat;
      final lng = activity.lng;
      // Numbering counts every included stop, plotted or not, so a stop the
      // planner couldn't geocode leaves a gap rather than shifting every
      // number after it out of step with the list.
      final current = order++;
      if (lat == null || lng == null) continue;
      stops.add(MappedStop(current, LatLng(lat, lng)));
    }
    if (stops.isNotEmpty) days.add(stops);
  }
  return days;
}

class _NumberedMarker extends StatelessWidget {
  const _NumberedMarker({required this.number, required this.color});

  final int number;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 2),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.25),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      alignment: Alignment.center,
      child: Text(
        '$number',
        style: AppTextStyles.caption.copyWith(
          color: Colors.white,
          fontWeight: FontWeight.w700,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _FigmaRoutePlaceholder extends StatelessWidget {
  const _FigmaRoutePlaceholder({required this.height});

  final double height;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: Container(
        height: height,
        width: double.infinity,
        decoration: BoxDecoration(
          color: const Color(0xFFF3F5F4),
          border: Border.all(color: AppColors.borderAlt),
        ),
        child: Image.asset('assets/images/final-route-map.png', fit: BoxFit.cover),
      ),
    );
  }
}
