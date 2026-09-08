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
class RouteMap extends StatefulWidget {
  const RouteMap({
    super.key,
    required this.itinerary,
    this.height = 300,
    this.onlyDay,
  });

  final Itinerary itinerary;
  final double height;

  /// Show just this day's stops. Null shows the whole trip.
  ///
  /// The day tabs above the map filter the stop list, and leaving every
  /// day's markers on the map while the list showed one made the two
  /// disagree about what the traveller had selected.
  final int? onlyDay;

  @override
  State<RouteMap> createState() => _RouteMapState();
}

class _RouteMapState extends State<RouteMap> {
  final MapController _controller = MapController();

  Itinerary get itinerary => widget.itinerary;
  double get height => widget.height;
  int? get onlyDay => widget.onlyDay;

  void _zoomBy(double delta) {
    final camera = _controller.camera;
    _controller.move(
      camera.center,
      (camera.zoom + delta).clamp(3.0, 18.0),
    );
  }

  /// [MapOptions.initialCameraFit] is consulted once, at the map's first
  /// layout, so a day tab that changes which stops are drawn leaves the
  /// camera framing the day before it — picking day 2 showed an empty patch
  /// of Seoul with its markers off-screen. Re-fit whenever the selection
  /// changes under a map that is already on screen.
  @override
  void didUpdateWidget(RouteMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.onlyDay == widget.onlyDay &&
        identical(oldWidget.itinerary, widget.itinerary)) {
      return;
    }

    final points = _pointsFor(widget);
    // Nothing to frame, or the previous build showed the illustration instead
    // of a map: in both cases there is no live FlutterMap bound to
    // _controller, and this frame's build sets the fit up correctly anyway.
    if (points.isEmpty || _pointsFor(oldWidget).isEmpty) return;

    final fit = _fitFor(points);
    if (fit == null) {
      _controller.move(points.first, 14);
    } else {
      _controller.fitCamera(fit);
    }
  }

  static List<LatLng> _pointsFor(RouteMap w) => [
        for (final day in mappableDays(w.itinerary, onlyDay: w.onlyDay))
          for (final stop in day) stop.point,
      ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final days = mappableDays(itinerary, onlyDay: onlyDay);
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
          // Without this the widget builds its own controller and
          // _controller is orphaned, so _zoomBy throws on every tap.
          mapController: _controller,
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
                      color: _dayColor(days[i].first.dayNumber),
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
                        color: _dayColor(stop.dayNumber),
                      ),
                    ),
              ],
            ),
          ],
            ),
            Positioned(
              right: 8,
              bottom: 8,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _ZoomButton(
                    icon: Icons.add,
                    tooltip: 'Zoom in',
                    onTap: () => _zoomBy(1),
                  ),
                  const SizedBox(height: 6),
                  _ZoomButton(
                    icon: Icons.remove,
                    tooltip: 'Zoom out',
                    onTap: () => _zoomBy(-1),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// The camera that frames [points], or null when there is no extent to fit
  /// — CameraFit.bounds on a zero-area box zooms to maxZoom on one building.
  static CameraFit? _fitFor(List<LatLng> points) {
    if (points.length < 2) return null;

    final lats = points.map((p) => p.latitude);
    final lngs = points.map((p) => p.longitude);
    return CameraFit.bounds(
      bounds: LatLngBounds(
        LatLng(lats.reduce((a, b) => a < b ? a : b),
            lngs.reduce((a, b) => a < b ? a : b)),
        LatLng(lats.reduce((a, b) => a > b ? a : b),
            lngs.reduce((a, b) => a > b ? a : b)),
      ),
      padding: const EdgeInsets.all(32),
    );
  }

  MapOptions _options(List<LatLng> points) {
    final fit = _fitFor(points);
    if (fit == null) {
      return MapOptions(
        initialCenter: points.first,
        initialZoom: 14,
        minZoom: 3,
        maxZoom: 18,
        interactionOptions: _interaction,
      );
    }

    return MapOptions(
      minZoom: 3,
      maxZoom: 18,
      interactionOptions: _interaction,
      initialCameraFit: fit,
    );
  }

  /// Pan, pinch, double-tap and scroll-wheel. Rotation stays off: the route
  /// reads against north, and a stray two-finger twist inside a scrolling
  /// list is far more often an accident than an intent.
  static const _interaction = InteractionOptions(
    flags: InteractiveFlag.pinchZoom |
        InteractiveFlag.drag |
        InteractiveFlag.doubleTapZoom |
        InteractiveFlag.scrollWheelZoom,
  );
}

/// A zoom control. Present because the map is only 128-200px tall inside a
/// scrolling list, where a pinch is both fiddly and easily taken for a scroll.
class _ZoomButton extends StatelessWidget {
  const _ZoomButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.sm),
          side: const BorderSide(color: AppColors.border),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppRadii.sm),
          child: SizedBox(
            width: 30,
            height: 30,
            child: Icon(icon, size: 17, color: AppColors.textPrimary),
          ),
        ),
      ),
    );
  }
}

/// Day 1 takes the first colour, day 2 the second, and so on — keyed off the
/// day number rather than list position so a filtered map keeps each day's
/// colour.
Color _dayColor(int dayNumber) =>
    kDayColors[(dayNumber - 1).clamp(0, 1 << 30) % kDayColors.length];

/// One plottable stop: its number in the printed route list, and where it is.
@visibleForTesting
class MappedStop {
  const MappedStop(this.order, this.point, this.dayNumber);
  final int order;
  final LatLng point;

  /// The itinerary day this stop belongs to. Drives its colour, so filtering
  /// to one day keeps that day the colour it had on the full-trip map.
  final int dayNumber;
}

/// Stops that can actually be plotted, grouped by day and numbered
/// continuously across the trip so the marker numbers line up with the route
/// list printed under the map.
@visibleForTesting
List<List<MappedStop>> mappableDays(Itinerary itinerary, {int? onlyDay}) {
  final days = <List<MappedStop>>[];
  var order = 1;

  for (final day in itinerary.days) {
    // Numbering still counts the skipped days, so a marker keeps the same
    // number whether the map is filtered or not.
    if (onlyDay != null && day.dayNumber != onlyDay) {
      order += day.activities.length;
      continue;
    }
    final stops = <MappedStop>[];
    for (final activity in day.activities) {
      final lat = activity.lat;
      final lng = activity.lng;
      // Numbering counts every stop the route list counts — switched off or
      // ungeocoded included — so a marker's number always names the same row
      // in that list. Skipping either from the count instead renumbered
      // everything after it and the two silently disagreed.
      final current = order++;
      if (!activity.included || lat == null || lng == null) continue;
      stops.add(MappedStop(current, LatLng(lat, lng), day.dayNumber));
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
