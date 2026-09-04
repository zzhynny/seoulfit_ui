import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';
import '../../widgets/progress_dots.dart';

class EnterNameScreen extends StatefulWidget {
  const EnterNameScreen({super.key, required this.onContinue, required this.onBack});

  final VoidCallback onContinue;
  final VoidCallback onBack;

  @override
  State<EnterNameScreen> createState() => _EnterNameScreenState();
}

class _EnterNameScreenState extends State<EnterNameScreen> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  IconButton(
                    onPressed: widget.onBack,
                    icon: const Icon(Icons.chevron_left, size: 28),
                  ),
                  const ProgressDots(step: 1),
                ],
              ),
            ),
            // Figma's 02_Enter-Name stacks a fixed 22px name-top spacer +
            // a fixed 206px spacer-top before the content block (not a
            // centering flex), then a flexible spacer-bottom before the
            // button — so the title sits at a fixed height, not hugging
            // the top bar.
            const SizedBox(height: 228),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Column(
                    children: [
                      Text(
                        "Hi there!\nWhat's your name?",
                        textAlign: TextAlign.center,
                        style: AppTextStyles.headingLarge,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        "We'll use it to personalize your Seoul itinerary.",
                        textAlign: TextAlign.center,
                        style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('FIRST NAME', style: AppTextStyles.labelUppercase),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _controller,
                        decoration: const InputDecoration(hintText: 'Alex'),
                        style: AppTextStyles.bodyLarge,
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const Expanded(child: SizedBox()),
            Padding(
              padding: const EdgeInsets.all(24),
              child: PrimaryButton(
                label: 'Continue',
                onPressed: () {
                  final name = _controller.text.trim();
                  context
                      .read<CompanionProvider>()
                      .setUserName(name.isEmpty ? 'Alex' : name);
                  widget.onContinue();
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
