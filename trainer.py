import os
import pickle
import copy
import torch
import torch.nn as nn
import torch.optim as optim

from .device import get_cpu_device
from .device import get_device
from .util import model_gradients_to_vector
from .validator import validator


class trainer:
    def __init__(
        self, model, loss_fun, training_dataset, name="",
    ):
        self.model = copy.deepcopy(model)
        self.loss_fun = loss_fun
        self.training_dataset = training_dataset
        self.name = name
        self.min_training_loss = None
        self.min_training_loss_model = None
        self.optimizer_fun = optim.Adam

    def set_optimizer_function(self, optimizer_fun):
        self.optimizer_fun = optimizer_fun

    def train(self, epochs, batch_size, learning_rate, **kwargs):
        training_data_loader = torch.utils.data.DataLoader(
            self.training_dataset, batch_size=batch_size, shuffle=True
        )

        device = get_device()
        self.model.to(device)
        optimizer = self.optimizer_fun(
            self.model.parameters(), lr=learning_rate)
        instance_size = len(self.training_dataset)

        batch_index = 0
        for epoch in range(epochs):
            self.model.train()
            training_loss = 0.0
            for batch in training_data_loader:
                self.model.to(device)
                optimizer.zero_grad()
                batch_loss = 0

                real_batch_size = batch[0].shape[0]
                if "pre_batch_callback" in kwargs:
                    kwargs["pre_batch_callback"](
                        self.model, batch, batch_index, learning_rate
                    )

                cur_batch_model = copy.deepcopy(self.model)
                if "per_instance_gradient_callback" in kwargs:
                    prev_accumulated_gradient = None
                    instance_inputs, instance_targets, instance_indices = batch
                    for i, instance_index in enumerate(instance_indices):
                        instance_index = instance_indices[i].data.item()
                        instance_input = instance_inputs[i].to(device)
                        instance_target = instance_targets[i].to(device)
                        output = self.model(torch.stack([instance_input]))
                        loss = self.loss_fun(
                            output, torch.stack(
                                [instance_target]))
                        batch_loss += loss.data.item() / real_batch_size
                        loss.backward()
                        cur_accumulated_gradient = model_gradients_to_vector(
                            self.model)
                        instance_gradient = None
                        if prev_accumulated_gradient is None:
                            instance_gradient = cur_accumulated_gradient
                        else:
                            instance_gradient = (
                                cur_accumulated_gradient - prev_accumulated_gradient)
                        prev_accumulated_gradient = cur_accumulated_gradient
                        del cur_accumulated_gradient

                        if "per_instance_gradient_callback" in kwargs:
                            kwargs["per_instance_gradient_callback"](
                                self.model,
                                instance_index,
                                instance_gradient,
                                learning_rate,
                                real_batch_size,
                            )
                    inputs = batch[0].to(device)
                    targets = batch[1].to(device)
                    outputs = cur_batch_model(inputs)
                    loss_fun = nn.CrossEntropyLoss(reduction='sum')
                    loss2 = loss_fun(outputs, targets)
                    loss2.backward()
                    test_gradient = model_gradients_to_vector(cur_batch_model)
                    prev_accumulated_gradient
                    if not torch.all(
                        torch.eq(prev_accumulated_gradient, test_gradient)
                    ):
                        print(prev_accumulated_gradient)
                        print(test_gradient)
                        print(torch.norm(prev_accumulated_gradient-test_gradient,2))
                        print(
                            torch.eq(
                                prev_accumulated_gradient,
                                test_gradient))
                        print("aaaaaaaaaaaaaaaa")
                        raise ValueError("invalid gradient")

                else:
                    inputs = batch[0].to(device)
                    targets = batch[1].to(device)
                    outputs = self.model(inputs)
                    loss = self.loss_fun(outputs, targets)
                    batch_loss = loss.data.item()
                    loss.backward()

                print(
                    "trainer:{}, epoch: {}, batch: {}, batch training loss: {}".format(
                        self.name, epoch, batch_index, batch_loss))

                optimizer.step()
                batch_index += 1
                training_loss += batch_loss * real_batch_size / instance_size

            print(
                "trainer:{}, epoch: {}, epoch training loss: {}".format(
                    self.name, epoch, training_loss
                )
            )

            if "validation_dataset" in kwargs:
                validation_epoch_interval = int(
                    kwargs.get("validation_epoch_interval", 1)
                )
                assert validation_epoch_interval > 0

                if epoch % validation_epoch_interval == 0:
                    validation_loss, accuracy = validator(
                        self.model, self.loss_fun, kwargs["validation_dataset"]
                    ).validate(batch_size)
                    print(
                        "trainer:{}, epoch: {}, validation loss: {}, accuracy = {}".format(
                            self.name, epoch, validation_loss.data.item(), accuracy
                        )
                    )

            if "after_epoch_callback" in kwargs:
                kwargs["after_epoch_callback"](self.model, epoch)
            if self.min_training_loss is None or training_loss < self.min_training_loss:
                self.min_training_loss = training_loss
                self.min_training_loss_model = copy.deepcopy(self.model)
                self.min_training_loss_model.to(get_cpu_device())

    def save(self, save_dir, save_min_model=False):
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        model = self.model
        if save_min_model:
            if self.min_training_loss_model:
                model = self.min_training_loss_model
            else:
                raise ValueError("no min model to save")
        model.to(get_cpu_device())
        torch.save(model, os.path.join(save_dir, "model.pt"))

    def save_dataset(self, save_dir):
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        open(os.path.join(save_dir, "training_dataset"), "wb").write(
            pickle.dumps(self.training_dataset)
        )

    def parameters(self, use_best_model=False):
        model = self.model
        if use_best_model:
            if self.min_training_loss_model:
                model = self.min_training_loss_model
            else:
                raise ValueError("no min model to use")

        model.to(get_cpu_device())
        return model.parameters()
