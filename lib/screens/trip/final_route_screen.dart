import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/day_tabs.dart';
import '../../widgets/poi_summary.dart';
import '../../widgets/itinerary_detail.dart';
import '../../widgets/route_map.dart';
import 'place_detail_sheet.dart';

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

  // Off by default: with the text on, a day of stops no longer fits between
  // the map and the hops. The full text is one tap away in the detail sheet.
  bool _showDescriptions = false;

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
    // The same day's activities, index-aligned with [stops]: the detail sheet
    // opens on a TripActivity, the one the itinerary screen's cards use.
    var activities = const <TripActivity>[];
    for (final day in itinerary.days) {
      final count = day.activities.length;
      if (day.dayNumber == selectedDay) {
        stops = itinerary.routeStops
            .skip(offset)
            .take(count)
            .toList(growable: false);
        activities = day.activities;
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
                    if (stops.isNotEmpty)
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton.icon(
                          onPressed: () => setState(
                              () => _showDescriptions = !_showDescriptions),
                          icon: Icon(
                            _showDescriptions
                                ? Icons.visibility_off_outlined
                                : Icons.notes,
                            size: 16,
                          ),
                          label: Text(_showDescriptions
                              ? 'Hide descriptions'
                              : 'Show descriptions'),
                          style: TextButton.styleFrom(
                            foregroundColor: AppColors.primary,
                            textStyle: AppTextStyles.caption
                                .copyWith(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ),
                    for (var i = 0; i < stops.length; i++) ...[
                      _PlaceStopCard(
                        stop: stops[i],
                        index: i + 1,
                        showDescription: _showDescriptions,
                        // Guarded: mock data can carry more stops than the
                        // day has activities.
                        onTap: i < activities.length
                            ? () => showPlaceDetailSheet(context, activities[i])
                            : null,
                      ),
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
  const _PlaceStopCard({
    required this.stop,
    required this.index,
    required this.showDescription,
    this.onTap,
  });

  final RouteStop stop;
  final int index;
  final bool showDescription;

  /// Opens the stop's detail sheet. Null only when there's no activity to
  /// open it on.
  final VoidCallback? onTap;

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

    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
      onTap: widget.onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
      width: double.infinity,
      // Was 16 all round with the name on two lines and a permanent hint row
      // underneath; a day of stops did not fit on a phone without the flow
      // between them scrolling out of sight.
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
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
                // What the place actually is, same source as the itinerary
                // cards: PoiSummary fetches /poi-summary and shows the
                // planner's note until it lands. ApiService memoises by name,
                // so a stop already seen on the itinerary screen costs nothing
                // here. Behind the screen's toggle and clipped to 2 lines --
                // this card is one of 5-8 in a scroll; the sheet has it whole.
                if (widget.showDescription) ...[
                  const SizedBox(height: 4),
                  PoiSummary(
                    name: stop.nameEn,
                    fallback: stop.description,
                    maxLines: 2,
                    style: AppTextStyles.caption
                        .copyWith(fontSize: 11, color: AppColors.textSecondary),
                  ),
                ],
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
      ),
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
            const SizedBox(height: 10),
            _RouteSteps(segments: hop.options.first.segments),
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

/// The leading option leg by leg, one line each.
///
/// These used to be joined with " → " into a single [Text] inside a
/// `Row(mainAxisSize: min)`, which hands its non-flex children an unbounded
/// main axis -- so a four-leg route ("🚇 Line 2  Gangnam → Hongik Univ
/// (25 min, 12 stops)" x4) blew the card out by 500+ pixels. A leg per row
/// is both the fix and the thing a traveller actually reads on the platform.
class _RouteSteps extends StatelessWidget {
  const _RouteSteps({required this.segments});

  final List<String> segments;

  /// ODsay prefixes each leg with 🚇/🚌/🚶. Swap it for the Material icon the
  /// rest of the card uses so the column doesn't read as two icon sets.
  static (IconData, String) _split(String segment) {
    const icons = {'🚇': Icons.train, '🚌': Icons.directions_bus, '🚶': Icons.directions_walk};
    for (final entry in icons.entries) {
      if (segment.startsWith(entry.key)) {
        return (entry.value, segment.substring(entry.key.length).trim());
      }
    }
    return (Icons.circle, segment);
  }

  @override
  Widget build(BuildContext context) {
    if (segments.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final segment in segments)
          Padding(
            padding: const EdgeInsets.only(bottom: 5),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: Icon(_split(segment).$1, size: 14, color: const Color(0xFF5E836A)),
                ),
                const SizedBox(width: 8),
                // Expanded, not bare Text: the leg names are long and the
                // row must wrap inside the card rather than run past it.
                Expanded(
                  child: Text(
                    _split(segment).$2,
                    style: AppTextStyles.caption.copyWith(
                      fontSize: 11.5,
                      height: 1.35,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// The leading option's numbers -- how many changes, the fare, how far you
/// still walk. Three different questions, so three slots with their own icons.
/// The leg list lives in [_RouteSteps]; anything here stays short enough to
/// sit side by side.
class _FactRow extends StatelessWidget {
  const _FactRow({required this.option});

  final TransitChoice option;

  @override
  Widget build(BuildContext context) {
    final facts = <(IconData, String)>[
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
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final (icon, text) in facts)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppColors.borderAlt),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 13, color: const Color(0xFF8A857D)),
                const SizedBox(width: 4),
                // Flexible + ellipsis: a Row this size hands a bare Text an
                // unbounded main axis, and unbounded is how the card
                // overflowed in the first place.
                Flexible(
                  child: Text(
                    text,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.caption
                        .copyWith(fontSize: 11, color: AppColors.textSecondary),
                  ),
                ),
              ],
            ),
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
