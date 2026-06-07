# generate_faiss.py
import os
import glob
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from app.config import settings

def main():
    # Define directories
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'ai', 'data')
    output_dir = os.path.join(base_dir, settings.FAISS_INDEX_PATH.lstrip('./'))
    
    print(f"Loading documents from: {data_dir}")
    documents = []
    
    # 1. Load PDF Files
    pdf_files = glob.glob(os.path.join(data_dir, '*.pdf'))
    for pdf_path in pdf_files:
        print(f"Loading PDF: {pdf_path}")
        try:
            loader = PyPDFLoader(pdf_path)
            documents.extend(loader.load())
        except Exception as e:
            print(f"Error loading PDF {pdf_path}: {e}")
            
    # 2. Load Text Files
    text_files = glob.glob(os.path.join(data_dir, '*.txt'))
    # Also include transfusion.data and transfusion.names if they contain text
    other_files = glob.glob(os.path.join(data_dir, '*.data')) + glob.glob(os.path.join(data_dir, '*.names'))
    all_txt = text_files + other_files
    
    for txt_path in all_txt:
        print(f"Loading Text file: {txt_path}")
        try:
            loader = TextLoader(txt_path, encoding='utf-8')
            documents.extend(loader.load())
        except Exception as e:
            try:
                # Fallback encoding
                loader = TextLoader(txt_path, encoding='latin-1')
                documents.extend(loader.load())
            except Exception as e2:
                print(f"Error loading text file {txt_path}: {e2}")
            
    print(f"Total documents loaded: {len(documents)}")
    if not documents:
        print("No documents found to index.")
        return
        
    # Split documents into chunks
    print("Splitting documents into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150
    )
    splits = text_splitter.split_documents(documents)
    print(f"Split into {len(splits)} chunks.")
    
    # Initialize embeddings
    print(f"Initializing embeddings model: {settings.EMBEDDINGS_MODEL}")
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.EMBEDDINGS_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    
    # Create FAISS vector store
    print("Building FAISS vector index...")
    vectorstore = FAISS.from_documents(splits, embeddings)
    
    # Save vector store locally
    print(f"Saving FAISS index to: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)
    vectorstore.save_local(output_dir)
    print("FAISS index generated and saved successfully!")

if __name__ == "__main__":
    main()
