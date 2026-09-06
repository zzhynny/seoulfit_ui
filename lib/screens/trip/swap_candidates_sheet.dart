import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../data/api/mappers.dart';
import '../../data/repositories/trip_repository.dart';
import '../../models/plan_check.dart';
import '../../models/trip.dart';
import '../../providers/trip_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/category_tag.dart';
import '../../widgets/poi_photo.dart';

/// Offers ranked replacements for one stop. Returns the chosen candidate's
/// name, or null if the traveller backed out.
Future<String?> showSwapCandidatesSheet(
  BuildContext context, {
  required TripDay day,
  required TripActivity activity,
}) {
  return showModalBottomSheet<String>(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (_) => SwapCandidatesSheet(day: day, activity: activity),
  );
}

class SwapCandidatesSheet extends StatefulWidget {
  const SwapCandidatesSheet({
    super.key,
    required this.day,
    required this.activity,
  });

  final TripDay day;
  final TripActivity activity;

  @override
  State<SwapCandidatesSheet> createState() => _SwapCandidatesSheetState();
}

class _SwapCandidatesSheetState extends State<SwapCandidatesSheet> {
  List<SwapCandidate>? _candidates;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final trip = context.read<TripProvider>();
    final repository = context.read<TripRepository>();

    // The backend ranks by slot position within the day, so send the index
    // this stop actually occupies rather than its position in any filtered
    // view.
    final slotIndex = widget.day.activities.indexOf(widget.activity);

    try {
      final candidates = await repository.fetchSwapCandidates(
        day: widget.day.dayNumber,
        slotIndex: slotIndex < 0 ? 0 : slotIndex,
        currentPoi: widget.activity.title,
        // The day's neighbourhood keeps a replacement within reach of the
        // stops either side of it.
        dayArea: widget.day.areaName,
        currentPoiType: widget.activity.poiType,
        // Never offer back something already dropped, or a stop already on
        // the plan.
        excludedIds: [
          for (final a in widget.day.activities) a.id,
          ...trip.pendingSwaps.values,
        ],
      );
      if (mounted) {
        setState(() {
          _candidates = candidates;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.4,
      maxChildSize: 0.9,
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
            Text('Swap this stop',
                style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Replacing ${widget.activity.title}',
              style: AppTextStyles.bodySmall
                  .copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.xl),
            ..._body(),
          ],
        ),
      ),
    );
  }

  List<Widget> _body() {
    if (_loading) {
      return const [
        Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.xxxl),
          child: Center(
            child: SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        ),
      ];
    }

    if (_error != null) {
      return [_Note('Could not reach the planner. Try again in a moment.')];
    }

    final candidates = _candidates ?? const <SwapCandidate>[];
    if (candidates.isEmpty) {
      // A real answer, not a failure: the planner found nothing of the same
      // kind nearby that isn't already on the plan.
      return [
        _Note('No alternatives nearby for this kind of stop. '
            'You can switch it off instead.'),
      ];
    }

    return [
      for (final candidate in candidates) ...[
        _CandidateRow(
          candidate: candidate,
          onPick: () => Navigator.of(context).pop(candidate.name),
        ),
        const SizedBox(height: AppSpacing.smMd),
      ],
    ];
  }
}

class _CandidateRow extends StatelessWidget {
  const _CandidateRow({required this.candidate, required this.onPick});

  final SwapCandidate candidate;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onPick,
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.smMd),
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(AppRadii.lg),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            PoiPhoto(name: candidate.name, type: candidate.type, size: 64),
            const SizedBox(width: AppSpacing.smMd),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Flexible(
                        child: Text(
                          candidate.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTextStyles.cardTitle,
                        ),
                      ),
                      CategoryTag(
                          category: categoryForPoiType(candidate.type)),
                    ],
                  ),
                  if (candidate.rating != null) ...[
                    const SizedBox(height: 2),
                    Text('${candidate.rating!.toStringAsFixed(1)}★',
                        style: AppTextStyles.caption
                            .copyWith(color: AppColors.textSecondary)),
                  ],
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    candidate.address,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTextStyles.bodySmall
                        .copyWith(color: AppColors.textSecondary),
                  ),
                  // Warnings inform rather than block — the ranking already
                  // took them into account.
                  for (final warning in candidate.warnings) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.warning_amber_rounded,
                            size: 14, color: AppColors.warning),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(warning,
                              style: AppTextStyles.caption
                                  .copyWith(color: AppColors.textSecondary)),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxl),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: AppTextStyles.bodyMedium
            .copyWith(color: AppColors.textSecondary, height: 1.5),
      ),
    );
  }
}
