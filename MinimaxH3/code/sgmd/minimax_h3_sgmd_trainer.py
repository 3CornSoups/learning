"""SGMD distillation for MiniMax-H3 text-to-audio-video generation."""

import os

import torch
from loguru import logger

from lightx2v_train.runtime.distributed import barrier, get_world_size, is_main_process, reduce_mean
from lightx2v_train.utils.registry import TRAINER_REGISTER

from .math import (
    negative_residual_loss_pair,
    normalized_fisher_loss_pair,
    normalized_x_pred_loss_pair,
    residual_contraction_loss_pair,
    teacher_stop_gradient_fisher_loss_pair,
    weighted_mse_pair,
)
from .minimax_h3_trainer import MiniMaxH3T2AVDmdTrainer


@TRAINER_REGISTER("minimax_h3_t2av_sgmd")
class MiniMaxH3T2AVSgmdTrainer(MiniMaxH3T2AVDmdTrainer):
    """Two-update SGMD for MiniMax-H3 joint video and audio generation."""

    trainer_name = "minimax_h3_t2av_sgmd"
    supports_ida = False
    fake_correction_weight = 0.1

    def __init__(self, config):
        super().__init__(config)
        if self.fake_update_ratio != 1:
            raise ValueError(
                "minimax_h3_t2av_sgmd strictly uses one student and one fake-score "
                "update per iteration; set training.dmd.fake_update_ratio=1."
            )
        sgmd_config = self.training_config.get("sgmd", {})
        self.fake_correction_weight = float(
            sgmd_config.get("fake_correction_weight", self.fake_correction_weight)
        )
        if self.fake_correction_weight <= 0:
            raise ValueError("training.sgmd.fake_correction_weight must be positive.")

    @staticmethod
    def _x0_from_velocity(latents, velocities, sigmas):
        """H3 predicts clean-ward velocity: x0 = xt + sigma * velocity."""
        return (
            latents[0] + sigmas[0] * velocities[0],
            latents[1] + sigmas[1] * velocities[1],
        )

    def _generator_forward(self, latent_shape, conditions, initial_noise=None):
        condition, _ = conditions
        end_step_idx = self._sample_synced_int(0, self.num_inference_steps)
        generated = self.run_back_simulation(
            condition,
            latent_shape,
            end_step_idx,
            grad_enabled=True,
            xt=initial_noise,
        )
        sigmas = self._sample_renoise_sigmas()
        noises = (
            torch.randn_like(generated[0], dtype=torch.float32),
            torch.randn_like(generated[1], dtype=torch.float32),
        )
        renoised = self._add_noise(generated, noises, sigmas)

        # Gradients must flow through fake predictions to the generated H3
        # latents, while fake parameters are discarded after this student step.
        self.fake_model.transformer.eval()
        velocity_fake = self._predict_velocity(
            self.fake_model,
            renoised,
            sigmas,
            condition,
            latent_shape,
        )
        with torch.no_grad():
            self.teacher_model.transformer.eval()
            velocity_teacher = self._predict_velocity(
                self.teacher_model,
                renoised,
                sigmas,
                condition,
                latent_shape,
            )
            x0_teacher = self._x0_from_velocity(renoised, velocity_teacher, sigmas)

        x0_fake = self._x0_from_velocity(renoised, velocity_fake, sigmas)
        # The paper objective uses the score-space coefficient
        # c(t)=(1-sigma)^2/sigma^4. Keep the normalized value as a
        # scale-invariant diagnostic only, not as the optimization objective.
        loss_fisher = teacher_stop_gradient_fisher_loss_pair(
            x0_fake,
            x0_teacher,
            sigmas,
            self.video_loss_weight,
            self.audio_loss_weight,
        )
        _, normalizers = normalized_fisher_loss_pair(
            generated,
            x0_fake,
            x0_teacher,
            self.video_loss_weight,
            self.audio_loss_weight,
        )
        loss_negative_residual = negative_residual_loss_pair(
            generated,
            x0_fake,
            self.video_loss_weight,
            self.audio_loss_weight,
        )
        loss_generator = loss_fisher + self.fake_correction_weight * loss_negative_residual
        score_context = (
            (generated[0].detach(), generated[1].detach()),
            noises,
            sigmas,
            condition,
            tuple(value.detach() for value in normalizers),
            latent_shape,
        )
        return {
            "generator": loss_generator,
            "fisher": loss_fisher.detach(),
            "negative_residual": loss_negative_residual.detach(),
            "sgmd_step": end_step_idx + 1,
        }, score_context

    def _fake_score_forward(self, score_context):
        generated, noises, sigmas, condition, normalizers, latent_shape = score_context
        renoised = self._add_noise(generated, noises, sigmas)
        self.fake_model.transformer.eval()
        velocity_fake = self._predict_velocity(
            self.fake_model,
            renoised,
            sigmas,
            condition,
            latent_shape,
        )
        target = (
            generated[0].float() - noises[0],
            generated[1].float() - noises[1],
        )
        loss_velocity = weighted_mse_pair(
            velocity_fake,
            target,
            self.video_loss_weight,
            self.audio_loss_weight,
        )
        x0_fake = self._x0_from_velocity(renoised, velocity_fake, sigmas)
        # Paper Eq. 22: update the fake score with λ·L_RC while the
        # generated student output is stop-gradient.
        loss_rc = self.fake_correction_weight * residual_contraction_loss_pair(
            generated,
            x0_fake,
            self.video_loss_weight,
            self.audio_loss_weight,
        )
        with torch.no_grad():
            loss_x_pred = normalized_x_pred_loss_pair(
                generated,
                x0_fake,
                normalizers,
                self.video_loss_weight,
                self.audio_loss_weight,
            )
        return {
            "score": loss_rc,
            "v_pred": loss_velocity.detach(),
            "rc": loss_rc.detach(),
            "x_pred": loss_x_pred.detach(),
        }

    def train(self):
        resume_ckpt_path, current_iter = self._resolve_resume()
        self.setup(resume_ckpt_path=resume_ckpt_path)
        if is_main_process():
            os.makedirs(self.output_train_dir, exist_ok=True)
        barrier()

        grad_accum_iters = max(1, int(self.gradient_accumulation_iters))
        logger.info(
            "[train] start method={} student_train_type={} fake_train_type={} "
            "iter={}/{} world_size={} grad_accum={} fake_update_ratio={} "
            "fake_correction_weight={}",
            self.trainer_name,
            self.student_train_type,
            self.fake_train_type,
            current_iter,
            self.max_train_iters,
            get_world_size(),
            grad_accum_iters,
            self.fake_update_ratio,
            self.fake_correction_weight,
        )

        samples = self._iter_train_samples()
        while current_iter < self.max_train_iters:
            self.optimizer.zero_grad(set_to_none=True)
            self.fake_optimizer.zero_grad(set_to_none=True)
            running_generator = running_fisher = running_negative_residual = running_step = 0.0
            score_contexts = []

            for micro_idx in range(grad_accum_iters):
                sample = next(samples)
                conditions = self._encode_conditions(sample)
                latent_shape = self._latent_shape(sample)
                sync_grad = micro_idx == grad_accum_iters - 1
                self._set_student_gradient_sync(sync_grad)
                self._set_fake_gradient_sync(False)
                result, score_context = self._generator_forward(
                    latent_shape,
                    conditions,
                    initial_noise=self.sample_initial_latents(latent_shape),
                )
                (result["generator"] / grad_accum_iters).backward()
                # Algorithm 1 uses this exact detached (x0, epsilon, sigma)
                # tuple for the subsequent fake-score RC update.
                score_contexts.append(score_context)
                running_generator += result["generator"].detach().item() / grad_accum_iters
                running_fisher += result["fisher"].item() / grad_accum_iters
                running_negative_residual += result["negative_residual"].item() / grad_accum_iters
                running_step += result["sgmd_step"] / grad_accum_iters
                del result

            self._sync_sequence_parallel_grads(self.trainable_params)
            torch.nn.utils.clip_grad_norm_(self.trainable_params, self.max_grad_norm)
            self.optimizer.step()
            self._after_student_optimizer_step("main")
            self.lr_scheduler.step()
            self.optimizer.zero_grad(set_to_none=True)
            # Fake accumulated input-gradient bookkeeping during the generator
            # step must never become a fake optimizer update.
            self.fake_optimizer.zero_grad(set_to_none=True)

            running_v_pred = running_rc = running_x_pred = 0.0
            for micro_idx, score_context in enumerate(score_contexts):
                sync_grad = micro_idx == grad_accum_iters - 1
                self._set_fake_gradient_sync(sync_grad)
                score_result = self._fake_score_forward(score_context)
                (score_result["score"] / grad_accum_iters).backward()
                running_v_pred += score_result["v_pred"].item() / grad_accum_iters
                running_rc += score_result["rc"].item() / grad_accum_iters
                running_x_pred += score_result["x_pred"].item() / grad_accum_iters
                del score_result, score_context

            self._sync_sequence_parallel_grads(self.fake_trainable_params)
            torch.nn.utils.clip_grad_norm_(self.fake_trainable_params, self.max_grad_norm)
            self.fake_optimizer.step()
            self.fake_lr_scheduler.step()
            self.fake_optimizer.zero_grad(set_to_none=True)

            current_iter += 1
            if (
                current_iter == 1
                or current_iter % self.train_log_every_iters == 0
                or current_iter >= self.max_train_iters
            ):
                display_generator = reduce_mean(running_generator)
                display_fisher = reduce_mean(running_fisher)
                display_negative_residual = reduce_mean(running_negative_residual)
                display_sgmd_step = reduce_mean(running_step)
                display_v_pred = reduce_mean(running_v_pred)
                display_rc = reduce_mean(running_rc)
                display_x_pred = reduce_mean(running_x_pred)
                current_lr = self.lr_scheduler.get_last_lr()[0]
                fake_lr = self.fake_lr_scheduler.get_last_lr()[0]
                logger.info(
                    "[train] iter={}/{} generator={:.6f} fisher={:.6f} "
                    "negative_residual={:.6f} sgmd_step={:.2f} v_pred={:.6f} "
                    "rc={:.6f} x_pred={:.6f} lr={:.8f} fake_lr={:.8f}",
                    current_iter,
                    self.max_train_iters,
                    display_generator,
                    display_fisher,
                    display_negative_residual,
                    display_sgmd_step,
                    display_v_pred,
                    display_rc,
                    display_x_pred,
                    current_lr,
                    fake_lr,
                )
                self.log_metrics(
                    {
                        "train/generator": display_generator,
                        "train/fisher": display_fisher,
                        "train/negative_residual": display_negative_residual,
                        "train/sgmd_step": display_sgmd_step,
                        "train/v_pred": display_v_pred,
                        "train/rc": display_rc,
                        "train/x_pred": display_x_pred,
                        "train/lr": current_lr,
                        "train/fake_lr": fake_lr,
                    },
                    step=current_iter,
                )

            if self.save_every_iters and current_iter % self.save_every_iters == 0:
                self.save_checkpoint(current_iter, self.save_total_limit)

        logger.info("[train] finished iter={}/{}", current_iter, self.max_train_iters)
