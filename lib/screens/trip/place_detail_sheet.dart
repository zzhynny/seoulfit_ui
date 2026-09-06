import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../models/trip.dart';
import '../../services/api_service.dart';
import '../../services/kakao_links.dart';
import '../../theme/theme.dart';
import '../../widgets/category_tag.dart';
import '../../widgets/poi_photo.dart';

/// Opens the detail sheet for one itinerary stop.
Future<void> showPlaceDetailSheet(BuildContext context, TripActivity activity) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (_) => PlaceDetailSheet(activity: activity),
  );
}

/// What a traveller needs standing in front of a stop: how to recognise it,
/// when it's open, and how to get there.
///
/// Both text fields are fetched on open rather than with the itinerary —
/// `/poi-detail` runs a Tavily lookup and `/poi-arrival-tip` a Gemini call,
/// so resolving them for every stop up front would add dozens of seconds to
/// itinerary generation for text most stops never get read. [ApiService]
/// memoises by name, so reopening a sheet is instant.
class PlaceDetailSheet extends StatefulWidget {
  const PlaceDetailSheet({super.key, required this.activity});

  final TripActivity activity;

  @override
  State<PlaceDetailSheet> createState() => _PlaceDetailSheetState();
}

class _PlaceDetailSheetState extends State<PlaceDetailSheet> {
  String? _arrivalTip;
  String? _detail;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiService?>();
    if (api == null) {
      setState(() => _loading = false);
      return;
    }

    final name = widget.activity.title;
    final type = widget.activity.poiType;
    try {
      // Two independent lookups — fire them together rather than making the
      // traveller wait for the sum.
      final results = await Future.wait([
        api.fetchPoiArrivalTip(name, type: type),
        api.fetchPoiDetail(name, type: type),
      ]);
      if (!mounted) return;
      setState(() {
        _arrivalTip = results[0];
        _detail = results[1];
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openInMaps() async {
    final lat = widget.activity.lat;
    final lng = widget.activity.lng;
    final name = widget.activity.title.trim();

    // A search, not a route: this sheet opens from the itinerary, where
    // there's no location fix to route *from*. kakaoRoute's by/{mode} scheme
    // reads an empty origin as a broken coordinate, so asking for directions
    // without one produces a dead link. Kakao does the routing once the app
    // has the user's own position.
    final uri = kakaoSearch(
      name.isEmpty && lat != null && lng != null ? '$lat,$lng' : name,
    );

    var ok = false;
    try {
      if (await canLaunchUrl(uri)) ok = await launchUrl(uri);
    } catch (_) {
      ok = false;
    }
    // Never a dead end: if nothing can open the link, show the address so it
    // can be copied by hand.
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(widget.activity.description)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final activity = widget.activity;

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
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                PoiPhoto(
                  name: activity.title,
                  type: activity.poiType,
                  asset: activity.imageAsset,
                  size: 72,
                ),
                const SizedBox(width: AppSpacing.smMd),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            activity.time,
                            style: AppTextStyles.caption.copyWith(
                              color: AppColors.primary,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          CategoryTag(category: activity.category),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(activity.title,
                          style: AppTextStyles.headingSmall
                              .copyWith(fontSize: 18)),
                    ],
                  ),
                ),
              ],
            ),
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
                icon: Icons.explore_outlined,
                title: "You've arrived when",
                body: _arrivalTip,
                emptyNote: 'No arrival tip for this stop yet.',
              ),
              _Section(
                icon: Icons.info_outline,
                title: 'Before you go',
                body: _detail,
                emptyNote: 'No visitor info for this stop yet.',
              ),
            ],
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton.icon(
              onPressed: _openInMaps,
              icon: const Icon(Icons.map_outlined, size: 18),
              label: const Text('Open in Kakao Map'),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.primary,
                side: const BorderSide(color: AppColors.primary),
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppRadii.lg),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.icon,
    required this.title,
    required this.body,
    required this.emptyNote,
  });

  final IconData icon;
  final String title;
  final String? body;
  final String emptyNote;

  @override
  Widget build(BuildContext context) {
    final text = (body ?? '').trim();
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
              color: text.isEmpty
                  ? AppColors.textSecondary
                  : AppColors.textPrimary,
              height: 1.55,
            ),
          ),
        ],
      ),
    );
  }
}
