import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/route_map.dart';

class FinalRouteScreen extends StatefulWidget {
  const FinalRouteScreen({
    super.key,
    required this.itinerary,
    required this.onResetItinerary,
    required this.onBack,
  });

  final Itinerary itinerary;
  final VoidCallback onResetItinerary;
  final VoidCallback onBack;

  @override
  State<FinalRouteScreen> createState() => _FinalRouteScreenState();
}

class _FinalRouteScreenState extends State<FinalRouteScreen> {
  bool _showTransitTip = true;

  @override
  Widget build(BuildContext context) {
    final itinerary = widget.itinerary;
    final trip = context.watch<TripProvider>();
    final selectedDay = itinerary.days.any((d) => d.dayNumber == trip.selectedDay)
        ? trip.selectedDay
        : (itinerary.days.isEmpty ? 1 : itinerary.days.first.dayNumber);

    // routeStops is one flat sequence across the whole trip, which rendered
    // every day's stops in a single scroll. Slice it back into the day the
    // tabs are showing, using each day's own length so the numbering stays
    // the trip-wide one printed on the map markers.
    var offset = 0;
    var stops = const <RouteStop>[];
    for (final day in itinerary.days) {
      final count = day.activities.length;
      if (day.dayNumber == selectedDay) {
        stops = itinerary.routeStops
            .skip(offset)
            .take(count)
            .toList(growable: false);
        break;
      }
      offset += count;
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              GestureDetector(
                onTap: widget.onBack,
                child: const Padding(
                  padding: EdgeInsets.only(right: 4),
                  child: Icon(Icons.chevron_left, size: 24, color: Color(0xFF2D2A26)),
                ),
              ),
              Expanded(
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text('Your Route', style: AppTextStyles.headingMedium.copyWith(fontSize: 24, color: const Color(0xFF2D2A26))),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            border: Border.all(color: const Color(0xFF5E836A)),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            '${stops.length + 4} stops planned',
                            style: AppTextStyles.caption.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Curated walking & transit guidance for your day',
                      style: AppTextStyles.bodySmall.copyWith(color: const Color(0xFF8A857D)),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 24),
            ],
          ),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.only(bottom: 8),
            children: [
              if (itinerary.days.length > 1)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: DayTabs(
                    days: itinerary.days,
                    selectedDay: selectedDay,
                    onSelect: trip.selectDay,
                  ),
                ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: RouteMap(itinerary: widget.itinerary),
              ),
              if (_showTransitTip)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(16, 10, 14, 10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFDFBF4),
                      border: Border.all(color: const Color(0xFFEFE8DB)),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('💳 Paying for transit in Seoul',
                                  style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
                              const SizedBox(height: 8),
                              _bullet('Tag your T-money or contactless card at readers'),
                              _bullet("Buses don't give change - use exact fare or card"),
                              _bullet('Single-journey tokens: refundable ₩500 deposit'),
                            ],
                          ),
                        ),
                        IconButton(
                          onPressed: () => setState(() => _showTransitTip = false),
                          icon: const Icon(Icons.close, size: 16),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(),
                        ),
                      ],
                    ),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    for (var i = 0; i < stops.length; i++) ...[
                      _PlaceStopCard(stop: stops[i], index: i + 1),
                      // Only between stops, and only when the planner
                      // actually routed the pair.
                      if (i < stops.length - 1 &&
                          stops[i].hop != null &&
                          stops[i].hop!.hasAnything)
                        _HopGuide(hop: stops[i].hop!),
                    ],
                  ],
                ),
              ),
              GestureDetector(
                onTap: widget.onResetItinerary,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: RichText(
                    textAlign: TextAlign.center,
                    text: TextSpan(
                      style: AppTextStyles.bodySmall.copyWith(color: const Color(0xFF888888)),
                      children: const [
                        TextSpan(text: 'Want to create a different plan? '),
                        TextSpan(
                          text: 'Reset itinerary',
                          style: TextStyle(decoration: TextDecoration.underline),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _bullet(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 6, right: 8),
            child: Container(width: 6, height: 6, decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle)),
          ),
          Expanded(child: Text(text, style: AppTextStyles.caption.copyWith(fontSize: 11))),
        ],
      ),
    );
  }
}

class _PlaceStopCard extends StatelessWidget {
  const _PlaceStopCard({required this.stop, required this.index});

  final RouteStop stop;
  final int index;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
            alignment: Alignment.center,
            child: Text('$index', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        stop.nameKo != null ? '${stop.nameEn}\n${stop.nameKo}' : stop.nameEn,
                        style: AppTextStyles.headingSmall.copyWith(fontSize: 16, color: const Color(0xFF2D2A26)),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(color: const Color(0xFFF4F0E8), borderRadius: BorderRadius.circular(10)),
                      child: Text(stop.arrivalTime, style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Text("📍 How do I know I'm here?", style: AppTextStyles.caption.copyWith(color: const Color(0xFF8A857D))),
                    const Icon(Icons.expand_more, size: 16, color: Color(0xFF8A857D)),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// How to get to the next stop.
///
/// Replaces a hardcoded "Subway (18m)" mockup with the planner's own leg.
/// Public-transport options come from ODsay and are routinely absent — the
/// backend skips it for stops within walking distance, and a spent daily
/// quota returns the same empty list — so walk and drive estimates are the
/// baseline and the option chips are the enhancement, never the other way
/// round.
class _HopGuide extends StatelessWidget {
  const _HopGuide({required this.hop});

  final TransitHop hop;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF3F5F4),
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (var i = 0; i < hop.options.length; i++)
                _ModeChip(
                  icon: hop.options[i].isSubway
                      ? Icons.train
                      : Icons.directions_bus,
                  label: _optionLabel(hop.options[i]),
                  // The backend returns options best-first, so the leading
                  // one is the recommendation.
                  primary: i == 0,
                ),
              if (hop.walkMinutes != null)
                _ModeChip(
                  icon: Icons.directions_walk,
                  label: '${hop.walkMinutes}m walk',
                  primary: hop.options.isEmpty,
                  onTap: _launcher(hop.kakaoWalkUrl),
                ),
              if (hop.carMinutes != null)
                _ModeChip(
                  icon: Icons.local_taxi_outlined,
                  label: '${hop.carMinutes}m drive',
                  onTap: _launcher(hop.kakaoCarUrl),
                ),
            ],
          ),
          if (hop.options.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              _detailLine(hop.options.first),
              style: AppTextStyles.bodySmall
                  .copyWith(color: AppColors.textSecondary),
            ),
          ] else if (hop.distanceKm != null) ...[
            const SizedBox(height: 10),
            Text(
              '${hop.distanceKm!.toStringAsFixed(1)} km away',
              style: AppTextStyles.bodySmall
                  .copyWith(color: AppColors.textSecondary),
            ),
          ],
        ],
      ),
    );
  }

  VoidCallback? _launcher(String? url) {
    if (url == null || url.isEmpty) return null;
    return () async {
      final uri = Uri.parse(url);
      try {
        if (await canLaunchUrl(uri)) await launchUrl(uri);
      } catch (_) {
        // Nothing to do — the chip still shows the estimate, which is the
        // part the traveller actually needs.
      }
    };
  }
}

String _optionLabel(TransitChoice option) {
  final minutes = option.totalMinutes;
  return minutes == null ? option.label : '${option.label} (${minutes}m)';
}

/// The leading option's specifics: which lines, how many changes, the fare,
/// and how far you still walk.
String _detailLine(TransitChoice option) {
  return [
    if (option.segments.isNotEmpty) option.segments.join(' → '),
    if (option.transfers != null && option.transfers! > 0)
      '${option.transfers} transfer${option.transfers == 1 ? "" : "s"}',
    if (option.fareWon != null) '\u20a9${option.fareWon}',
    if (option.walkMeters != null && option.walkMeters! > 0)
      '${option.walkMeters}m walk',
  ].join(' \u00b7 ');
}

class _ModeChip extends StatelessWidget {
  const _ModeChip({
    required this.icon,
    required this.label,
    this.primary = false,
    this.onTap,
  });

  final IconData icon;
  final String label;
  final bool primary;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final fg = primary ? Colors.white : const Color(0xFF66615B);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: primary ? const Color(0xFF5E836A) : Colors.white,
          border: primary ? null : Border.all(color: AppColors.borderAlt),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: fg),
            const SizedBox(width: 6),
            Text(label,
                style: AppTextStyles.caption
                    .copyWith(color: fg, fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}
