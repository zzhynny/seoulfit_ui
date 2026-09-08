import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/itinerary_detail.dart';
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
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: DayTabs(
                    days: itinerary.days,
                    selectedDay: selectedDay,
                    onSelect: trip.selectDay,
                  ),
                ),
              Builder(builder: (context) {
                final day = itinerary.days
                    .where((d) => d.dayNumber == selectedDay)
                    .firstOrNull;
                if (day == null || day.estimatedCost.trim().isEmpty) {
                  return const SizedBox(height: 4);
                }
                return Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: DayCostChip(estimatedCost: day.estimatedCost),
                );
              }),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: RouteMap(
                  itinerary: widget.itinerary,
                  onlyDay: selectedDay,
                ),
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
              if (itinerary.sources.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: SourcesCard(sources: itinerary.sources),
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

class _PlaceStopCard extends StatefulWidget {
  const _PlaceStopCard({required this.stop, required this.index});

  final RouteStop stop;
  final int index;

  @override
  State<_PlaceStopCard> createState() => _PlaceStopCardState();
}

class _PlaceStopCardState extends State<_PlaceStopCard> {
  bool _expanded = false;

  RouteStop get stop => widget.stop;
  int get index => widget.index;

  @override
  Widget build(BuildContext context) {
    // The arrival hint was a chevron with no handler, over an
    // exitInstruction the model carried and nothing ever rendered.
    final hint = stop.exitInstruction?.trim();
    final hasHint = hint != null && hint.isNotEmpty;

    return Container(
      width: double.infinity,
      // Was 16 all round with the name on two lines and a permanent hint row
      // underneath; a day of stops did not fit on a phone without the flow
      // between them scrolling out of sight.
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 24,
            height: 24,
            decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
            alignment: Alignment.center,
            child: Text('$index', style: AppTextStyles.caption.copyWith(fontSize: 11, color: Colors.white, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            stop.nameEn,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: AppTextStyles.headingSmall.copyWith(fontSize: 15, color: const Color(0xFF2D2A26)),
                          ),
                          if (stop.nameKo != null)
                            Text(
                              stop.nameKo!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: AppTextStyles.caption.copyWith(fontSize: 11, color: const Color(0xFF8A857D)),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(color: const Color(0xFFF4F0E8), borderRadius: BorderRadius.circular(8)),
                      child: Text(stop.arrivalTime, style: AppTextStyles.caption.copyWith(fontSize: 11, fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
                    ),
                  ],
                ),
                // Only where the planner actually said something. An expander
                // that opens onto nothing is the same dead affordance again.
                if (hasHint) ...[
                  const SizedBox(height: 6),
                  InkWell(
                    onTap: () => setState(() => _expanded = !_expanded),
                    child: Row(
                      children: [
                        Text("📍 How do I know I'm here?", style: AppTextStyles.caption.copyWith(fontSize: 11, color: const Color(0xFF8A857D))),
                        Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 15, color: const Color(0xFF8A857D)),
                      ],
                    ),
                  ),
                  if (_expanded) ...[
                    const SizedBox(height: 4),
                    Text(
                      hint,
                      style: AppTextStyles.caption.copyWith(fontSize: 11, color: AppColors.textSecondary),
                    ),
                  ],
                ],
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
          Row(
            children: [
              const Icon(Icons.route_outlined, size: 13, color: Color(0xFF8A857D)),
              const SizedBox(width: 5),
              Text(
                hop.options.isNotEmpty ? 'BEST WAY THERE' : 'GETTING THERE',
                style: AppTextStyles.caption.copyWith(
                  fontSize: 10,
                  letterSpacing: 0.8,
                  fontWeight: FontWeight.w700,
                  color: const Color(0xFF8A857D),
                ),
              ),
              const Spacer(),
              if (hop.distanceKm != null)
                Text(
                  '${hop.distanceKm!.toStringAsFixed(1)} km',
                  style: AppTextStyles.caption.copyWith(
                    fontSize: 10,
                    color: const Color(0xFF8A857D),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),

          // The recommendation on its own line, at full width, so it is not
          // one of four look-alike chips the eye has to rank for itself.
          if (hop.options.isNotEmpty)
            TransportChip(
              icon: hop.options.first.isSubway ? Icons.train : Icons.directions_bus,
              label: _optionLabel(hop.options.first),
              primary: true,
              fullWidth: true,
              onTap: _launcher(hop.kakaoTransitUrl),
            ),

          if (hop.options.isNotEmpty) ...[
            const SizedBox(height: 8),
            _FactRow(option: hop.options.first),
          ],

          // Everything else is an alternative, and reads like one.
          if (_alternatives.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(spacing: 6, runSpacing: 6, children: _alternatives),
          ],
        ],
      ),
    );
  }

  List<Widget> get _alternatives => [
        for (var i = 1; i < hop.options.length; i++)
          TransportChip(
            icon: hop.options[i].isSubway ? Icons.train : Icons.directions_bus,
            label: _optionLabel(hop.options[i]),
            onTap: _launcher(hop.kakaoTransitUrl),
          ),
        if (hop.walkMinutes != null)
          TransportChip(
            icon: Icons.directions_walk,
            label: '${hop.walkMinutes}m walk',
            primary: hop.options.isEmpty,
            fullWidth: hop.options.isEmpty,
            onTap: _launcher(hop.kakaoWalkUrl),
          ),
        if (hop.carMinutes != null)
          TransportChip(
            icon: Icons.local_taxi_outlined,
            label: '${hop.carMinutes}m drive',
            onTap: _launcher(hop.kakaoCarUrl),
          ),
      ];

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

String _won(int fare) {
  final digits = fare.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return '₩$buffer';
}

/// The leading option's specifics. These used to be joined with middle dots
/// into a single grey run of text -- which lines, how many changes, the fare
/// and how far you still walk are four different questions, so they get four
/// slots with their own icons.
class _FactRow extends StatelessWidget {
  const _FactRow({required this.option});

  final TransitChoice option;

  @override
  Widget build(BuildContext context) {
    final facts = <(IconData, String)>[
      if (option.segments.isNotEmpty)
        (Icons.timeline, option.segments.join(' → ')),
      if (option.transfers != null && option.transfers! > 0)
        (Icons.swap_horiz,
            '${option.transfers} transfer${option.transfers == 1 ? "" : "s"}'),
      if (option.fareWon != null)
        (Icons.payments_outlined, _won(option.fareWon!)),
      if (option.walkMeters != null && option.walkMeters! > 0)
        (Icons.directions_walk, '${option.walkMeters}m walk'),
    ];
    if (facts.isEmpty) return const SizedBox.shrink();

    return Wrap(
      spacing: 12,
      runSpacing: 6,
      children: [
        for (final (icon, text) in facts)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 13, color: const Color(0xFF8A857D)),
              const SizedBox(width: 4),
              Text(
                text,
                style: AppTextStyles.caption
                    .copyWith(fontSize: 11, color: AppColors.textSecondary),
              ),
            ],
          ),
      ],
    );
  }
}

/// One way of getting to the next stop.
///
/// Public so a widget test can sweep every chip on screen and assert none of
/// them is a dead button: the subway and bus chips used to render with no
/// [onTap] at all while looking exactly like the ones that opened Kakao.
class TransportChip extends StatelessWidget {
  const TransportChip({
    super.key,
    required this.icon,
    required this.label,
    this.primary = false,
    this.fullWidth = false,
    this.onTap,
  });

  final IconData icon;
  final String label;
  final bool primary;
  final bool fullWidth;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final fg = primary ? Colors.white : const Color(0xFF66615B);
    return Material(
      color: primary ? const Color(0xFF5E836A) : Colors.white,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          height: fullWidth ? 40 : 32,
          width: fullWidth ? double.infinity : null,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            border: primary ? null : Border.all(color: AppColors.borderAlt),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            mainAxisSize: fullWidth ? MainAxisSize.max : MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: fg),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTextStyles.caption.copyWith(
                    color: fg,
                    fontWeight: FontWeight.w700,
                    fontSize: fullWidth ? 13 : null,
                  ),
                ),
              ),
              if (fullWidth && onTap != null) ...[
                const Spacer(),
                Icon(Icons.open_in_new, size: 14, color: fg),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
