import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/event.dart';
import '../../services/api_service.dart';
import '../../services/kakao_links.dart';
import '../../theme/theme.dart';

/// Opens the detail sheet for one event card.
Future<void> showEventDetailSheet(BuildContext context, SeoulEvent event) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (_) => EventDetailSheet(event: event),
  );
}

/// What the grid can't show: what the event actually is, when it runs, what it
/// costs, and where to go.
///
/// Fetched on open rather than with the grid — the list is 80 events and the
/// detail is two 한국관광공사 TourAPI calls each, so resolving it up front would
/// be 160 calls for text most events never get read. [ApiService] memoises by
/// contentid, so reopening a sheet paints on its first frame.
///
/// TourAPI fills these fields unevenly (venue on nearly every event, the
/// description on about half), so every row falls back to its own note rather
/// than the sheet assuming a populated response.
class EventDetailSheet extends StatefulWidget {
  const EventDetailSheet({super.key, required this.event});

  final SeoulEvent event;

  @override
  State<EventDetailSheet> createState() => _EventDetailSheetState();
}

class _EventDetailSheetState extends State<EventDetailSheet> {
  Map<String, String> _detail = const {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    final cid = widget.event.contentId;
    // Mock data carries no contentid — there is nothing to fetch, and the
    // sheet still shows the title, date and venue the card already had.
    if (cid == null) {
      _loading = false;
      return;
    }
    final saved = context.read<ApiService?>()?.cachedEventDetail(cid);
    if (saved != null) {
      _detail = saved;
      _loading = false;
      return;
    }
    _load(cid);
  }

  Future<void> _load(String contentId) async {
    final api = context.read<ApiService?>();
    if (api == null) {
      setState(() => _loading = false);
      return;
    }
    try {
      final detail = await api.fetchEventDetail(contentId);
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _field(String key) => (_detail[key] ?? '').trim();

  Future<void> _launch(Uri uri, String whatFailed) async {
    var ok = false;
    try {
      if (await canLaunchUrl(uri)) {
        ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
    } catch (_) {
      ok = false;
    }
    if (!ok && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text("Couldn't open $whatFailed.")));
    }
  }

  /// A search, not a route: the events tab has no location fix to route *from*.
  /// Kakao does the routing once it has the user's own position.
  Future<void> _openInMaps() {
    final event = widget.event;
    // The event's own venue name beats the street address — TourAPI's English
    // service still returns some addresses in Hangul.
    final place = _field('place');
    final query = place.isNotEmpty
        ? place
        : (event.venue.trim().isNotEmpty ? event.venue.trim() : event.title);
    return _launch(kakaoSearch(query), 'Kakao Map');
  }

  @override
  Widget build(BuildContext context) {
    final event = widget.event;
    final homepage = _field('homepage');
    final coords = event.lat != null && event.lng != null
        ? LatLng(event.lat!, event.lng!)
        : null;

    return DraggableScrollableSheet(
      initialChildSize: 0.62,
      minChildSize: 0.4,
      maxChildSize: 0.92,
      expand: false,
      builder: (context, scrollController) => Container(
        decoration: const BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        child: ListView(
          controller: scrollController,
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.xxl, AppSpacing.smMd, AppSpacing.xxl, AppSpacing.xxl),
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.border,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
            if (event.dateRange.isNotEmpty)
              Text(
                event.dateRange,
                style: AppTextStyles.caption.copyWith(
                  color: const Color(0xFFA67C68),
                  fontWeight: FontWeight.w700,
                ),
              ),
            const SizedBox(height: AppSpacing.xs),
            Text(event.title,
                style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
            const SizedBox(height: AppSpacing.xl),
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.xxl),
                child: Center(
                  child: SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
              )
            else ...[
              _Section(
                icon: Icons.info_outline,
                title: 'About',
                body: _field('overview'),
                emptyNote: 'No description published for this event yet.',
              ),
              _Row(
                icon: Icons.place_outlined,
                label: 'Venue',
                value: _field('place').isNotEmpty ? _field('place') : event.venue,
              ),
              _Row(
                icon: Icons.schedule,
                label: 'Hours',
                value: _field('hours'),
              ),
              _Row(
                icon: Icons.confirmation_number_outlined,
                label: 'Admission',
                value: _field('fee'),
              ),
              _Row(
                icon: Icons.people_outline,
                label: 'Age',
                value: _field('age_limit'),
              ),
              _Row(
                icon: Icons.call_outlined,
                label: 'Enquiries',
                value: _field('tel'),
              ),
              if (_field('program').isNotEmpty)
                _Section(
                  icon: Icons.list_alt,
                  title: 'Programme',
                  body: _field('program'),
                  emptyNote: '',
                ),
            ],
            const SizedBox(height: AppSpacing.sm),
            if (coords != null)
              OutlinedButton.icon(
                onPressed: _openInMaps,
                icon: const Icon(Icons.map_outlined, size: 18),
                label: const Text('Open in Kakao Map'),
                style: _buttonStyle,
              ),
            if (homepage.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              OutlinedButton.icon(
                onPressed: () => _launch(Uri.parse(homepage), 'the event site'),
                icon: const Icon(Icons.language, size: 18),
                label: const Text('Official site'),
                style: _buttonStyle,
              ),
            ],
            if (event.landingUrl != null) ...[
              const SizedBox(height: AppSpacing.sm),
              OutlinedButton.icon(
                onPressed: () =>
                    _launch(Uri.parse(event.landingUrl!), event.title),
                icon: const Icon(Icons.open_in_new, size: 18),
                label: const Text('View on VisitKorea'),
                style: _buttonStyle,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

final _buttonStyle = OutlinedButton.styleFrom(
  foregroundColor: AppColors.primary,
  side: const BorderSide(color: AppColors.primary),
  minimumSize: const Size.fromHeight(48),
  shape: RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(AppRadii.lg),
  ),
);

/// A block of prose. Mirrors the stop sheet's section so the two read alike.
class _Section extends StatelessWidget {
  const _Section({
    required this.icon,
    required this.title,
    required this.body,
    required this.emptyNote,
  });

  final IconData icon;
  final String title;
  final String body;
  final String emptyNote;

  @override
  Widget build(BuildContext context) {
    final text = body.trim();
    if (text.isEmpty && emptyNote.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: AppColors.textSecondary),
              const SizedBox(width: AppSpacing.sm),
              Text(title, style: AppTextStyles.labelUppercase),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            text.isEmpty ? emptyNote : text,
            style: AppTextStyles.bodyMedium.copyWith(
              color:
                  text.isEmpty ? AppColors.textSecondary : AppColors.textPrimary,
              height: 1.55,
            ),
          ),
        ],
      ),
    );
  }
}

/// One labelled fact. Hidden entirely when TourAPI has nothing — a column of
/// "not available" rows is worse than a shorter sheet.
class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.label, required this.value});

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final text = value.trim();
    if (text.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.smMd),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.sm),
          SizedBox(
            width: 78,
            child: Text(label, style: AppTextStyles.labelUppercase),
          ),
          Expanded(
            child: Text(
              text,
              style: AppTextStyles.bodyMedium.copyWith(
                color: AppColors.textPrimary,
                height: 1.45,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
