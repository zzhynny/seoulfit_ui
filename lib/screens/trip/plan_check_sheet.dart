import 'package:flutter/material.dart';

import '../../models/plan_check.dart';
import '../../theme/theme.dart';

/// Shows the critic's verdict on the plan either side of the repair pass.
Future<void> showPlanCheckSheet(BuildContext context, ReoptimizeResult result) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (_) => PlanCheckSheet(result: result),
  );
}

/// The output of Critic → Repair → Critic, made visible.
///
/// The planner already ran all three passes and threw the verdict away at the
/// UI boundary; a traveller could not tell whether "Optimize" had fixed
/// anything, or whether something was still wrong with their plan.
class PlanCheckSheet extends StatelessWidget {
  const PlanCheckSheet({super.key, required this.result});

  final ReoptimizeResult result;

  @override
  Widget build(BuildContext context) {
    final fixed = result.fixed;
    final remaining = result.remaining;

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
            Text('Plan check',
                style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
            const SizedBox(height: AppSpacing.xl),

            _ScoreRow(
              label: 'Can you actually do it',
              // Feasibility, not the blended overall score: it's the only
              // term that speaks to whether the days are completable —
              // meal windows, travel time and opening hours.
              before: result.before.feasibilityScore,
              after: result.after.feasibilityScore,
            ),
            const SizedBox(height: AppSpacing.smMd),
            _ScoreRow(
              label: 'Overall',
              before: result.before.overallScore,
              after: result.after.overallScore,
            ),
            const SizedBox(height: AppSpacing.xxl),

            if (fixed.isEmpty && remaining.isEmpty)
              _CleanNote()
            else ...[
              if (fixed.isNotEmpty) ...[
                _SectionLabel('Fixed automatically'),
                for (final issue in fixed)
                  _IssueCard(issue: issue, resolved: true),
                const SizedBox(height: AppSpacing.lg),
              ],
              if (remaining.isNotEmpty) ...[
                _SectionLabel('Still needs your attention'),
                for (final issue in remaining)
                  _IssueCard(issue: issue, resolved: false),
                const SizedBox(height: AppSpacing.lg),
              ],
            ],

            if (result.repairLog.isNotEmpty) ...[
              _SectionLabel('What changed'),
              for (final line in result.repairLog)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('• ', style: AppTextStyles.bodySmall),
                      Expanded(
                        child: Text(line,
                            style: AppTextStyles.bodySmall.copyWith(
                                color: AppColors.textSecondary, height: 1.5)),
                      ),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.smMd),
      child: Text(text, style: AppTextStyles.labelUppercase),
    );
  }
}

class _ScoreRow extends StatelessWidget {
  const _ScoreRow({
    required this.label,
    required this.before,
    required this.after,
  });

  final String label;
  final double? before;
  final double? after;

  @override
  Widget build(BuildContext context) {
    // A plan the critic never scored shows nothing rather than a
    // reassuring-looking zero.
    if (after == null) return const SizedBox.shrink();

    final improved = before != null && after! > before!;
    return Row(
      children: [
        Expanded(
          child: Text(label,
              style: AppTextStyles.bodyMedium
                  .copyWith(color: AppColors.textSecondary)),
        ),
        if (before != null && before != after) ...[
          _ScorePill(score: before!, muted: true),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
            child: Icon(
              improved ? Icons.arrow_forward : Icons.arrow_forward,
              size: 14,
              color: AppColors.textSecondary,
            ),
          ),
        ],
        _ScorePill(score: after!),
      ],
    );
  }
}

class _ScorePill extends StatelessWidget {
  const _ScorePill({required this.score, this.muted = false});

  final double score;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    // Thresholds match the critic's own reading of its 0..1 scale: below 0.6
    // the plan has something a traveller will actually run into.
    final color = muted
        ? AppColors.textSecondary
        : score >= 0.8
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
      child: Text(
        score.toStringAsFixed(2),
        style: AppTextStyles.caption
            .copyWith(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _IssueCard extends StatelessWidget {
  const _IssueCard({required this.issue, required this.resolved});

  final PlanIssue issue;
  final bool resolved;

  @override
  Widget build(BuildContext context) {
    final accent = resolved ? AppColors.success : AppColors.accent;
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.smMd),
      decoration: BoxDecoration(
        color: resolved ? AppColors.primaryTint : AppColors.accentTint,
        borderRadius: BorderRadius.circular(AppRadii.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            resolved ? Icons.check_circle_outline : Icons.error_outline,
            size: 16,
            color: accent,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  issue.message,
                  style: AppTextStyles.bodySmall.copyWith(height: 1.45),
                ),
                if (issue.day != null || (issue.area ?? '').isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    [
                      if (issue.day != null) 'Day ${issue.day}',
                      if ((issue.area ?? '').isNotEmpty) issue.area!,
                    ].join(' · '),
                    style: AppTextStyles.caption
                        .copyWith(color: AppColors.textSecondary),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CleanNote extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.primaryTint,
        borderRadius: BorderRadius.circular(AppRadii.md),
      ),
      child: Row(
        children: [
          const Icon(Icons.check_circle_outline,
              size: 18, color: AppColors.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text('No issues found — your plan looks solid.',
                style: AppTextStyles.bodyMedium),
          ),
        ],
      ),
    );
  }
}
