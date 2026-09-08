import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/trip.dart';
import '../theme/theme.dart';

/// The planner's prose description of the trip.
class TripSummaryText extends StatelessWidget {
  const TripSummaryText({super.key, required this.summary});

  final String summary;

  @override
  Widget build(BuildContext context) {
    if (summary.trim().isEmpty) return const SizedBox.shrink();
    return Text(
      summary.trim(),
      style: AppTextStyles.bodyMedium.copyWith(
        color: AppColors.textSecondary,
        height: 1.55,
      ),
    );
  }
}

/// The critic's verdict, as a compact chip.
///
/// Shows feasibility, not the blended overall score, for the same reason the
/// plan-check sheet leads with it: feasibility is the term that says whether
/// the days can actually be completed — meal windows, travel time between
/// stops, opening hours — while `overall` folds in area coverage and
/// foreigner-readiness, which say nothing about that. [overall] is shown
/// alongside only when it differs.
class PlanScoreChip extends StatelessWidget {
  const PlanScoreChip({super.key, required this.feasibility, this.overall});

  final double? feasibility;
  final double? overall;

  @override
  Widget build(BuildContext context) {
    final score = feasibility ?? overall;
    // A plan the critic never scored shows nothing, rather than a
    // reassuring-looking zero.
    if (score == null) return const SizedBox.shrink();

    // Same thresholds the plan-check sheet uses: below 0.6 the plan has
    // something the traveller will actually run into.
    final color = score >= 0.8
        ? AppColors.success
        : score >= 0.6
            ? AppColors.warning
            : AppColors.accent;

    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadii.sm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.verified_outlined, size: 13, color: color),
          const SizedBox(width: 5),
          Text(
            feasibility != null ? 'Doable ${_pct(score)}' : _pct(score),
            style: AppTextStyles.caption
                .copyWith(color: color, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }

  static String _pct(double score) => '${(score * 100).round()}%';
}

/// The planner's cost estimate for one day.
class DayCostChip extends StatelessWidget {
  const DayCostChip({super.key, required this.estimatedCost});

  final String estimatedCost;

  @override
  Widget build(BuildContext context) {
    if (estimatedCost.trim().isEmpty) return const SizedBox.shrink();
    return Row(
      children: [
        const Icon(Icons.payments_outlined,
            size: 14, color: AppColors.textSecondary),
        const SizedBox(width: AppSpacing.xs),
        Expanded(
          child: Text(
            estimatedCost.trim(),
            style:
                AppTextStyles.caption.copyWith(color: AppColors.textSecondary),
          ),
        ),
      ],
    );
  }
}

/// Where this itinerary came from.
///
/// The plan is assembled from published courses, and showing them lets a
/// traveller check the trip against its source rather than taking a
/// generated plan on trust.
class SourcesCard extends StatelessWidget {
  const SourcesCard({super.key, required this.sources});

  final List<TripSource> sources;

  @override
  Widget build(BuildContext context) {
    if (sources.isEmpty) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(AppRadii.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.verified_user_outlined,
                  size: 14, color: AppColors.primary),
              const SizedBox(width: AppSpacing.sm),
              Text('Sources', style: AppTextStyles.labelUppercase),
            ],
          ),
          const SizedBox(height: AppSpacing.smMd),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              for (final source in sources)
                _SourceChip(
                  label: source.courseTitle.isNotEmpty
                      ? source.courseTitle
                      : source.source,
                  publisher: source.source,
                  url: source.sourceUrl,
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({
    required this.label,
    required this.publisher,
    required this.url,
  });

  final String label;
  final String publisher;
  final String url;

  Future<void> _open(BuildContext context) async {
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    var ok = false;
    try {
      if (await canLaunchUrl(uri)) ok = await launchUrl(uri);
    } catch (_) {
      ok = false;
    }
    // Never a dead end — show the address so it can be copied by hand.
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(url)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final linked = url.trim().isNotEmpty;
    return GestureDetector(
      onTap: linked ? () => _open(context) : null,
      child: Container(
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.smMd, vertical: AppSpacing.sm),
        decoration: BoxDecoration(
          color: AppColors.chipBackground,
          borderRadius: BorderRadius.circular(AppRadii.sm),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTextStyles.bodySmall.copyWith(
                  color: AppColors.primaryDark,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            if (linked) ...[
              const SizedBox(width: AppSpacing.xs),
              const Icon(Icons.open_in_new,
                  size: 12, color: AppColors.primaryDark),
            ],
          ],
        ),
      ),
    );
  }
}
