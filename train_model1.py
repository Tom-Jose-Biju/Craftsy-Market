import tensorflow as tf
from tensorflow.keras.applications import EfficientNetV2B0
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.callbacks import ReduceLROnPlateau, EarlyStopping
from PIL import Image
import numpy as np
import os
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "craftsy.settings")
django.setup()

# Now import your Django models
from accounts.models import Product

# Image parameters
img_width, img_height = 224, 224
batch_size = 32

def load_image(x):
    if isinstance(x, np.ndarray):
        return x
    elif isinstance(x, str):
        try:
            with Image.open(x) as img:
                img = img.convert('RGB')
                img = img.resize((img_width, img_height))
                return np.array(img)
        except Exception as e:
            print(f"Error loading image {x}: {str(e)}")
            return None
    else:
        print(f"Unsupported input type: {type(x)}")
        return None

def preprocess_image(x):
    try:
        img = load_image(x)
        if img is None:
            return np.zeros((img_height, img_width, 3))  # Return a blank image
        return img
    except Exception as e:
        print(f"Error preprocessing image: {str(e)}")
        return np.zeros((img_height, img_width, 3))  # Return a blank image on error

def create_model(num_classes):
    base_model = EfficientNetV2B0(weights='imagenet', include_top=False, input_shape=(img_width, img_height, 3))
    x = base_model.output
    x = GlobalAveragePooling2D()(x)
    x = Dense(1024, activation='relu')(x)
    outputs = Dense(num_classes, activation='softmax')(x)
    model = Model(inputs=base_model.input, outputs=outputs)
    
    # Freeze the base model layers
    for layer in base_model.layers:
        layer.trainable = False
    
    return model

def safe_flow_from_directory(generator, *args, **kwargs):
    max_retries = 5
    retries = 0
    while retries < max_retries:
        try:
            return generator.flow_from_directory(*args, **kwargs)
        except Exception as e:
            print(f"Error in flow_from_directory (attempt {retries + 1}): {str(e)}")
            retries += 1
            # Find and remove the problematic file
            for root, dirs, files in os.walk(args[0]):
                for file in files:
                    try:
                        img_path = os.path.join(root, file)
                        with Image.open(img_path) as img:
                            img.verify()
                            img.load()
                    except Exception as img_error:
                        print(f"Removing corrupted image: {img_path}")
                        print(f"Error: {str(img_error)}")
                        os.remove(img_path)
            print("Retrying flow_from_directory after removing corrupted images...")
    raise ValueError("Max retries reached. Unable to process the dataset.")

def train_model(train_dir, validation_dir, num_classes, epochs=50, batch_size=32):
    model = create_model(num_classes)
    
    model.compile(optimizer=Adam(learning_rate=0.001),
                  loss='categorical_crossentropy',
                  metrics=['accuracy'])
    
    train_datagen = ImageDataGenerator(
        rescale=1./255,
        rotation_range=40,
        width_shift_range=0.2,
        height_shift_range=0.2,
        shear_range=0.2,
        zoom_range=0.2,
        horizontal_flip=True,
        vertical_flip=True,
        brightness_range=[0.7, 1.3],
        preprocessing_function=preprocess_image,
        fill_mode='nearest'
    )
    
    validation_datagen = ImageDataGenerator(
        rescale=1./255,
        preprocessing_function=preprocess_image
    )
    
    train_generator = safe_flow_from_directory(
        train_datagen,
        train_dir,
        target_size=(img_width, img_height),
        batch_size=batch_size,
        class_mode='categorical'
    )
    
    validation_generator = safe_flow_from_directory(
        validation_datagen,
        validation_dir,
        target_size=(img_width, img_height),
        batch_size=batch_size,
        class_mode='categorical'
    )
    
    reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.2, patience=5, min_lr=0.00001)
    early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
    
    history = None
    try:
        history = model.fit(
            train_generator,
            steps_per_epoch=train_generator.samples // batch_size,
            epochs=epochs,
            validation_data=validation_generator,
            validation_steps=validation_generator.samples // batch_size,
            callbacks=[reduce_lr, early_stopping]
        )
    except Exception as e:
        print(f"Error during model training: {str(e)}")
        print("Skipping initial training phase.")
    
    # Fine-tuning
    for layer in model.layers[-20:]:
        layer.trainable = True
    
    model.compile(optimizer=Adam(learning_rate=0.0001),
                  loss='categorical_crossentropy',
                  metrics=['accuracy'])
    
    try:
        history_fine = model.fit(
            train_generator,
            steps_per_epoch=train_generator.samples // batch_size,
            epochs=30,
            validation_data=validation_generator,
            validation_steps=validation_generator.samples // batch_size,
            callbacks=[reduce_lr, early_stopping]
        )
        # If fine-tuning succeeds, use its history
        history = history_fine
    except Exception as e:
        print(f"Error during model fine-tuning: {str(e)}")
    
    return model, history

# Usage
train_dir = 'dataset/train'
validation_dir = 'dataset/validation'
num_classes = len(Product.CATEGORY_CHOICES)

model, history = train_model(train_dir, validation_dir, num_classes)
model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'custom_efficientnetv2_model.h5')
model.save(model_path)
print(f"Model training completed and saved as '{model_path}'")
